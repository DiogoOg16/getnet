import inspect
import logging
import time
import unicodedata

from dataclasses import dataclass

logger = logging.getLogger("getnet_orchestrator")

from app.agents.customer_support import CustomerSupportAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent, RoutingDecision
from app.agents.web_search import WebSearchAgent
from app.tools.registry import ToolRegistry, tool_registry
from app.verified_facts import consolidate_verified_facts


@dataclass(frozen=True)
class PlanStep:
    """One explicit step in a planned agent execution."""

    agent: str
    reason: str


@dataclass(frozen=True)
class ExecutionPlan:
    """Bounded execution plan produced before running agents."""

    steps: tuple[PlanStep, ...]
    max_steps: int = 3


@dataclass(frozen=True)
class StepTrace:
    agent: str
    reason: str
    status: str
    tool_used: str | None = None
    request_id: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class ChatExecution:
    decision: RoutingDecision
    result: dict
    plan: ExecutionPlan
    executed_steps: tuple[str, ...]
    trace: tuple[StepTrace, ...] = ()


class ChatOrchestrator:
    """Plan, execute, and record a bounded agent workflow."""

    def __init__(self, *, registry: ToolRegistry | None = None) -> None:
        self.registry = registry if registry is not None else tool_registry
        if not isinstance(self.registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry instance.")
        self.router = RouterAgent()
        self.knowledge = KnowledgeAgent()
        self.support = CustomerSupportAgent(registry=self.registry)
        self.web_search = WebSearchAgent()

    @staticmethod
    def _with_context(message: str, conversation_context: list[str] | None = None) -> str:
        if not conversation_context:
            return message

        context_lines = [
            line.strip()
            for line in conversation_context
            if isinstance(line, str) and line.strip()
        ]
        if not context_lines:
            return message

        return (
            "Contexto recente da conversa:\n"
            + "\n".join(context_lines)
            + "\n\nPergunta atual: "
            + message
        )

    @staticmethod
    def _normalize_text(message: str) -> str:
        normalized = unicodedata.normalize("NFKD", message.casefold())
        return "".join(
            char for char in normalized
            if not unicodedata.combining(char)
        )

    @classmethod
    def _needs_knowledge_followup(cls, message: str) -> bool:
        text = cls._normalize_text(message)

        mentions_decline = any(
            term in text
            for term in ("recusad", "negad", "declin")
        )
        asks_for_guidance = any(
            term in text
            for term in (
                "por que", "porque", "como resolver",
                "como corrigir", "o que fazer",
                "why", "how to fix", "how can i",
            )
        )

        return mentions_decline and asks_for_guidance

    def create_plan(
        self,
        message: str,
        routing_context: str | None = None,
    ) -> tuple[RoutingDecision, ExecutionPlan]:
        decision = self.router.route(message, routing_context)

        steps = [
            PlanStep(
                agent=decision.agent,
                reason=decision.reason,
            )
        ]

        if (
            decision.agent == "customer_support"
            and self._needs_knowledge_followup(message)
        ):
            steps.append(
                PlanStep(
                    agent="knowledge",
                    reason=(
                        "Retrieve documented guidance for the declined "
                        "transaction after checking customer support data."
                    ),
                )
            )

        plan = ExecutionPlan(
            steps=tuple(steps[:3]),
            max_steps=3,
        )

        return decision, plan

    def _execute_step(
        self,
        step: PlanStep,
        message: str,
        user_id: str,
        verified_facts: list[dict] | None = None,
    ) -> dict:
        if step.agent == "knowledge":
            parameters = inspect.signature(self.knowledge.answer).parameters
            if "verified_facts" in parameters or any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            ):
                return self.knowledge.answer(message, verified_facts=verified_facts)
            return self.knowledge.answer(message)

        if step.agent == "customer_support":
            return self.support.answer(message=message, user_id=user_id)

        if step.agent == "web_search":
            return self.web_search.answer(message)

        if step.agent == "human_escalation":
            return {
                "agent": "human_escalation",
                "response": (
                    "Solicitação fora do escopo ou sensível. "
                    "Encaminho para atendimento humano para continuidade segura."
                ),
                "sources": [],
                "tool_used": "human_escalation",
                "handoff_required": True,
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": False,
                "awaiting_user_input": False,
                "step_status": "handoff",
            }

        return {
            "agent": "fallback",
            "response": (
                "Não consegui identificar sua solicitação com segurança. "
                "Você pode perguntar sobre produtos e serviços Getnet, "
                "informações externas ou um problema específico da sua "
                "conta ou transação."
            ),
            "sources": [],
            "tool_used": None,
            "handoff_required": False,
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "awaiting_user_input": False,
            "step_status": "failed",
        }

    @staticmethod
    def _summarize_conflicts(conflicts: list[dict]) -> str:
        summaries: list[str] = []
        for conflict in conflicts:
            values: list[str] = []
            for item in conflict.get("values", []):
                if isinstance(item, dict):
                    values.append(str(item.get("value")))
                else:
                    values.append(str(item))
            summaries.append(
                f"{conflict.get('entity', '')}::{conflict.get('name', '')}={', '.join(values)}"
            )
        return "; ".join(summaries)

    def _combine_results(self, results: list[dict]) -> dict:
        all_verified_facts: list[dict] = []
        for result in results:
            all_verified_facts.extend(result.get("verified_facts", []))

        consolidated_facts, fact_conflicts = consolidate_verified_facts(all_verified_facts)

        if len(results) == 1:
            merged = dict(results[0])
            merged.setdefault("flow_completed", True)
            merged.setdefault(
                "response_delivered",
                bool(merged.get("response", "").strip()),
            )
            merged.setdefault("issue_resolved", bool(merged.get("resolved", False)))
            merged["resolved"] = bool(
                merged.get("issue_resolved", merged.get("resolved", False))
            )
            merged.setdefault("awaiting_user_input", False)
            merged["verified_facts"] = consolidated_facts
            merged["fact_conflicts"] = fact_conflicts
            if fact_conflicts:
                merged["issue_resolved"] = False
                merged["resolved"] = False
                merged["step_status"] = "conflict"
                merged["response"] = (
                    "Há um conflito de fatos verificados na execução atual: "
                    + self._summarize_conflicts(fact_conflicts)
                    + ". Não foi possível confirmar um valor final sem resolução."
                )
            elif not merged.get("step_status"):
                if merged.get("handoff_required", False):
                    merged["step_status"] = "handoff"
                elif merged.get("awaiting_user_input", False):
                    merged["step_status"] = "waiting_for_user_input"
                elif merged.get("response_delivered", False):
                    merged["step_status"] = "success"
                else:
                    merged["step_status"] = "failed"
            return merged

        responses = [
            result["response"].strip()
            for result in results
            if result.get("response", "").strip()
        ]

        sources: list[str] = []
        source_sections: dict[str, list[str]] = {}
        tools: list[str] = []

        for result in results:
            for item in result.get("sources", []):
                if item not in sources:
                    sources.append(item)

            for section, items in result.get("source_sections", {}).items():
                section_items = source_sections.setdefault(section, [])
                for item in items:
                    if item not in section_items:
                        section_items.append(item)

            tool = result.get("tool_used")
            if tool:
                for name in tool.split(", "):
                    if name not in tools:
                        tools.append(name)

        any_awaiting = any(
            result.get("awaiting_user_input", False) for result in results
        )
        any_handoff = any(
            result.get("handoff_required", False) for result in results
        )
        any_failed = any(
            result.get("step_status") == "failed" for result in results
        )
        any_resolution = any(
            result.get("issue_resolved", result.get("resolved", False)) is True
            for result in results
        )

        if fact_conflicts:
            step_status = "conflict"
            any_resolution = False
            response = (
                "Há um conflito de fatos verificados na execução atual: "
                + self._summarize_conflicts(fact_conflicts)
                + ". Não foi possível confirmar um valor final sem resolução."
            )
        elif any_failed:
            step_status = "failed"
            response = "\n\nOrientações da base de conhecimento:\n".join(responses)
        elif any_handoff:
            step_status = "handoff"
            response = "\n\nOrientações da base de conhecimento:\n".join(responses)
        elif any_awaiting:
            step_status = "waiting_for_user_input"
            response = "\n\nOrientações da base de conhecimento:\n".join(responses)
        elif any_resolution or responses:
            step_status = "success"
            response = "\n\nOrientações da base de conhecimento:\n".join(responses)
        else:
            step_status = "failed"
            response = "\n\nOrientações da base de conhecimento:\n".join(responses)

        return {
            "agent": "multi_agent",
            "response": response,
            "sources": sources,
            "source_sections": source_sections,
            "tool_used": ", ".join(tools) if tools else None,
            "flow_completed": True,
            "response_delivered": bool(responses) or bool(fact_conflicts),
            "issue_resolved": not fact_conflicts and any_resolution,
            "resolved": not fact_conflicts and any_resolution,
            "handoff_required": any_handoff,
            "awaiting_user_input": any_awaiting,
            "step_status": step_status,
            "verified_facts": consolidated_facts,
            "fact_conflicts": fact_conflicts,
        }

    def handle(
        self,
        message: str,
        user_id: str,
        request_id: str | None = None,
        routing_context: str | None = None,
        conversation_context: list[str] | None = None,
    ) -> ChatExecution:
        current_message = message
        execution_message = self._with_context(current_message, conversation_context)
        if routing_context is None:
            decision, plan = self.create_plan(current_message)
        else:
            decision, plan = self.create_plan(current_message, routing_context)

        executed_steps: list[str] = []
        results: list[dict] = []
        trace: list[StepTrace] = []
        shared_verified_facts: list[dict] = []

        for step in plan.steps[:plan.max_steps]:
            step_started_at = time.perf_counter()
            try:
                step_result = self._execute_step(
                    step,
                    execution_message,
                    user_id,
                    verified_facts=shared_verified_facts,
                )
                shared_verified_facts.extend(step_result.get("verified_facts", []))
                results.append(step_result)
                executed_steps.append(step.agent)

                duration_ms = int((time.perf_counter() - step_started_at) * 1000)
                trace.append(
                    StepTrace(
                        agent=step.agent,
                        reason=step.reason,
                        status="success",
                        tool_used=step_result.get("tool_used"),
                        request_id=request_id,
                        duration_ms=duration_ms,
                    )
                )
                logger.info(
                    "orchestrator_step_complete request_id=%s agent=%s status=%s duration_ms=%s tool_used=%s",
                    request_id,
                    step.agent,
                    "success",
                    duration_ms,
                    step_result.get("tool_used"),
                )

                if step_result.get("handoff_required", False):
                    break

                if step_result.get("awaiting_user_input", False):
                    break

                if step_result.get("step_status") == "failed":
                    break

                # Keep progressing while there are planned valid steps unless
                # an operational terminal state was reached.
                if step_result.get("step_status") in {"handoff", "waiting_for_user_input"}:
                    break

            except Exception:
                duration_ms = int((time.perf_counter() - step_started_at) * 1000)
                trace.append(
                    StepTrace(
                        agent=step.agent,
                        reason=step.reason,
                        status="error",
                        request_id=request_id,
                        duration_ms=duration_ms,
                    )
                )
                logger.info(
                    "orchestrator_step_complete request_id=%s agent=%s status=%s duration_ms=%s tool_used=%s",
                    request_id,
                    step.agent,
                    "error",
                    duration_ms,
                    None,
                )
                results.append(
                    {
                        "agent": "fallback",
                        "response": (
                            "Ocorreu uma falha durante o atendimento. "
                            "Tente novamente ou solicite atendimento humano."
                        ),
                        "sources": [],
                        "tool_used": None,
                        "handoff_required": False,
                        "flow_completed": True,
                        "response_delivered": True,
                        "issue_resolved": False,
                        "awaiting_user_input": False,
                        "step_status": "failed",
                    }
                )
                break

        if results:
            result = self._combine_results(results)
        else:
            result = {
                "agent": "fallback",
                "response": (
                    "Não foi possível concluir a solicitação dentro "
                    "dos limites de execução."
                ),
                "sources": [],
                "tool_used": None,
                "handoff_required": False,
                "flow_completed": True,
                "response_delivered": False,
                "issue_resolved": False,
                "awaiting_user_input": False,
                "step_status": "failed",
            }

        return ChatExecution(
            decision=decision,
            result=result,
            plan=plan,
            executed_steps=tuple(executed_steps),
            trace=tuple(trace),
        )

