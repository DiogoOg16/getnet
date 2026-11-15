import inspect
import logging
import time
import unicodedata

from dataclasses import dataclass

logger = logging.getLogger("getnet_orchestrator")

from app.agents.customer_support import (
    TERMINAL_CONNECTIVITY_FLOW,
    CustomerSupportAgent,
)
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent, RoutingDecision
from app.agents.web_search import WebSearchAgent
from app.privacy import mask_sensitive
from app.tools.registry import ToolRegistry, tool_registry
from app.verified_facts import consolidate_verified_facts


KNOWLEDGE_HEADING = "Orientações da base de conhecimento:"

# Consulta fixa da etapa acrescentada depois de uma transação negada sem motivo.
# Menciona emissor e bandeira (quem autoriza a venda com cartão) para recuperar
# só o documento de status das vendas com cartão (L48); as formulações neutras
# também traziam o documento de status do Pix (L49), que não se aplica aqui.
# Não contém "status" + "venda", que acionaria a resposta direta do Knowledge.
DECLINED_SALE_QUERY = (
    "O que significa quando uma venda com cartão é negada pelo emissor ou pela bandeira?"
)
DECLINED_SALE_HEADING = (
    "O que significa uma venda negada, segundo a documentação Getnet "
    "(explicação geral; não é o motivo registrado desta transação):"
)


@dataclass(frozen=True)
class PlanStep:
    """One explicit step in a planned agent execution.

    `query` substitui a mensagem do usuário como entrada do agente;
    `share_facts` controla se a etapa recebe os fatos verificados anteriores;
    `heading` introduz a resposta da etapa quando ela é combinada com outras.
    """

    agent: str
    reason: str
    query: str | None = None
    share_facts: bool = True
    heading: str | None = None


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
    def _generation_context(conversation_history: list[str] | None = None) -> str:
        """Falas recentes do usuário para a geração; nunca entram em busca ou ferramentas.

        As respostas anteriores do assistente ficam de fora: recusas antigas
        ("não encontrei informações") induziam o modelo a recusar de novo.
        """
        lines = [
            line.strip()
            for line in conversation_history or []
            if isinstance(line, str) and line.strip().startswith("Usuário:")
        ]
        return "\n".join(lines)

    def _resumes_pending_flow(
        self,
        decision: RoutingDecision,
        message: str,
        pending_followup: dict | None,
    ) -> bool:
        if not pending_followup:
            return False
        if pending_followup.get("flow") != TERMINAL_CONNECTIVITY_FLOW:
            return False
        return self.router.continues_pending_flow(decision, message)

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

    @staticmethod
    def _followup_step(step: PlanStep, result: dict) -> PlanStep | None:
        """Decide a próxima etapa a partir do resultado verificado da anterior (ARCH-02).

        | Resultado de lookup_transaction | Próxima etapa |
        |---|---|
        | aprovada ou pendente | nenhuma |
        | negada, com motivo registrado | nenhuma (o Support já informa o motivo verificado) |
        | negada, sem motivo registrado | Knowledge, para o significado geral de venda negada |
        | erro, resultado inválido ou transação não encontrada | nenhuma |

        A etapa acrescentada não recebe os fatos da transação, para que a
        explicação geral não seja apresentada como causa desta transação.
        """
        if step.agent != "customer_support":
            return None
        if result.get("step_status") != "success" or result.get("tool_used") != "lookup_transaction":
            return None
        if result.get("decline_reason_recorded") is not False:
            return None
        declined = any(
            fact.get("name") == "status"
            and fact.get("value") == "declined"
            and fact.get("source_tool") == "lookup_transaction"
            for fact in result.get("verified_facts", [])
        )
        if not declined:
            return None
        return PlanStep(
            agent="knowledge",
            reason=(
                "lookup_transaction returned a declined transaction with no recorded "
                "reason; retrieve the documented general meaning of a declined sale."
            ),
            query=DECLINED_SALE_QUERY,
            share_facts=False,
            heading=DECLINED_SALE_HEADING,
        )

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
        generation_context: str = "",
        resumed_followup: dict | None = None,
    ) -> dict:
        if step.agent == "knowledge":
            parameters = inspect.signature(self.knowledge.answer).parameters
            accepts_any = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters.values()
            )
            kwargs = {}
            if step.share_facts and ("verified_facts" in parameters or accepts_any):
                kwargs["verified_facts"] = verified_facts
            if generation_context and (
                "generation_context" in parameters or accepts_any
            ):
                kwargs["generation_context"] = generation_context
            return self.knowledge.answer(message, **kwargs)

        if step.agent == "customer_support":
            if resumed_followup:
                return self.support.escalate_terminal_connectivity(
                    resumed_followup.get("original_message", ""),
                    message,
                )
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

    def _combine_results(
        self,
        results: list[dict],
        headings: list[str | None] | None = None,
    ) -> dict:
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

        headings = list(headings or [])
        headings += [None] * (len(results) - len(headings))
        # (cabeçalho, texto) de cada etapa com resposta. A primeira resposta
        # entra sem cabeçalho; as seguintes, com o cabeçalho da etapa ou o padrão.
        sections = [
            (heading or KNOWLEDGE_HEADING, result["response"].strip())
            for result, heading in zip(results, headings)
            if result.get("response", "").strip()
        ]
        responses = [text for _, text in sections]
        composed = "".join(
            text if position == 0 else f"\n\n{heading}\n{text}"
            for position, (heading, text) in enumerate(sections)
        )

        sources: list[str] = []
        source_sections: dict[str, list[str]] = {}

        for result in results:
            for item in result.get("sources", []):
                if item not in sources:
                    sources.append(item)

            for section, items in result.get("source_sections", {}).items():
                section_items = source_sections.setdefault(section, [])
                for item in items:
                    if item not in section_items:
                        section_items.append(item)

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
            response = composed
        elif any_handoff:
            step_status = "handoff"
            response = composed
        elif any_awaiting:
            step_status = "waiting_for_user_input"
            response = composed
        elif any_resolution or responses:
            step_status = "success"
            response = composed
        else:
            step_status = "failed"
            response = composed

        return {
            # Execução multi-etapa: agent e tool_used representam a etapa principal
            # (a primeira); o trace registra todos os agentes e ferramentas.
            "agent": results[0].get("agent", "fallback"),
            "response": response,
            "sources": sources,
            "source_sections": source_sections,
            "tool_used": results[0].get("tool_used"),
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
        pending_followup: dict | None = None,
    ) -> ChatExecution:
        current_message = message
        conversation_history = conversation_context
        # Referências curtas ("e essa?") usam somente a pergunta anterior já
        # resolvida; o histórico completo não vira consulta nem argumento.
        # SEC-01: só o roteador (create_plan, abaixo) lê o texto original, porque
        # precisa dele para detectar CPF/cartão. Todo agente — e, por meio deles,
        # o LLM, as ferramentas e a busca externa — recebe a versão mascarada.
        # Os documentos recuperados e os resultados das ferramentas não passam
        # por aqui e ficam intactos.
        agent_message = mask_sensitive(routing_context or current_message)
        # A geração só recebe histórico quando a pergunta depende dele: em
        # pergunta nova, falas antigas faziam o modelo recusar sem motivo.
        generation_context = (
            self._generation_context(conversation_history)
            if routing_context
            else ""
        )

        if routing_context is None:
            decision, plan = self.create_plan(current_message)
        else:
            decision, plan = self.create_plan(current_message, routing_context)

        resumed_followup = None
        if self._resumes_pending_flow(decision, current_message, pending_followup):
            resumed_followup = pending_followup
            decision = RoutingDecision(
                agent="customer_support",
                reason="The message continues a support flow awaiting user details.",
            )
            plan = ExecutionPlan(
                steps=(PlanStep(agent=decision.agent, reason=decision.reason),),
                max_steps=3,
            )

        executed_steps: list[str] = []
        results: list[dict] = []
        headings: list[str | None] = []
        trace: list[StepTrace] = []
        shared_verified_facts: list[dict] = []
        # O plano pode crescer durante a execução (_followup_step), sempre
        # limitado a max_steps e sem repetir um agente já planejado.
        steps: list[PlanStep] = list(plan.steps[:plan.max_steps])

        index = 0
        while index < len(steps):
            step = steps[index]
            index += 1
            step_started_at = time.perf_counter()
            try:
                step_result = self._execute_step(
                    step,
                    step.query or agent_message,
                    user_id,
                    verified_facts=shared_verified_facts,
                    generation_context=generation_context,
                    resumed_followup=resumed_followup,
                )
                shared_verified_facts.extend(step_result.get("verified_facts", []))
                results.append(step_result)
                headings.append(step.heading)
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

                followup = self._followup_step(step, step_result)
                if (
                    followup is not None
                    and len(steps) < plan.max_steps
                    and all(planned.agent != followup.agent for planned in steps)
                ):
                    steps.append(followup)
                    logger.info(
                        "orchestrator_step_added request_id=%s agent=%s after=%s",
                        request_id,
                        followup.agent,
                        step.agent,
                    )

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
                headings.append(None)
                break

        if results:
            result = self._combine_results(results, headings)
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
            plan=ExecutionPlan(steps=tuple(steps), max_steps=plan.max_steps),
            executed_steps=tuple(executed_steps),
            trace=tuple(trace),
        )

