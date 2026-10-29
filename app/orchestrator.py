import unicodedata

from dataclasses import dataclass

from app.agents.customer_support import CustomerSupportAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent, RoutingDecision
from app.agents.web_search import WebSearchAgent


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


@dataclass(frozen=True)
class ChatExecution:
    decision: RoutingDecision
    result: dict
    plan: ExecutionPlan
    executed_steps: tuple[str, ...]
    trace: tuple[StepTrace, ...] = ()


class ChatOrchestrator:
    """Plan, execute, and record a bounded agent workflow."""

    def __init__(self) -> None:
        self.router = RouterAgent()
        self.knowledge = KnowledgeAgent()
        self.support = CustomerSupportAgent()
        self.web_search = WebSearchAgent()

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

    def create_plan(self, message: str) -> tuple[RoutingDecision, ExecutionPlan]:
        decision = self.router.route(message)

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

    def _execute_step(self, step: PlanStep, message: str, user_id: str) -> dict:
        if step.agent == "knowledge":
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

    def _combine_results(self, results: list[dict]) -> dict:
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
            if not merged.get("step_status"):
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

        if any_failed:
            step_status = "failed"
        elif any_handoff:
            step_status = "handoff"
        elif any_awaiting:
            step_status = "waiting_for_user_input"
        elif any_resolution or responses:
            step_status = "success"
        else:
            step_status = "failed"

        return {
            "agent": "multi_agent",
            "response": "\n\nOrientações da base de conhecimento:\n".join(
                responses
            ),
            "sources": sources,
            "source_sections": source_sections,
            "tool_used": ", ".join(tools) if tools else None,
            "flow_completed": True,
            "response_delivered": bool(responses),
            "issue_resolved": any_resolution,
            "resolved": any_resolution,
            "handoff_required": any_handoff,
            "awaiting_user_input": any_awaiting,
            "step_status": step_status,
        }

    def handle(self, message: str, user_id: str) -> ChatExecution:
        decision, plan = self.create_plan(message)

        executed_steps: list[str] = []
        results: list[dict] = []
        trace: list[StepTrace] = []

        for step in plan.steps[:plan.max_steps]:
            try:
                step_result = self._execute_step(step, message, user_id)
                results.append(step_result)
                executed_steps.append(step.agent)

                trace.append(
                    StepTrace(
                        agent=step.agent,
                        reason=step.reason,
                        status="success",
                        tool_used=step_result.get("tool_used"),
                    )
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
                trace.append(
                    StepTrace(
                        agent=step.agent,
                        reason=step.reason,
                        status="error",
                    )
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

