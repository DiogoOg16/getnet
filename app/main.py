import hmac
import logging
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.agents.router import RoutingDecision
from app.auth import authenticate_user
from app.human_handoff import HumanHandoffStore, is_attendant_user
from app.orchestrator import ChatOrchestrator
from app.session_memory import SessionMemory
from app.tools.customer_tools import register_customer_tools
from app.tools.registry import tool_registry
from app.verified_facts import public_fact_conflicts, public_verified_facts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("getnet_api")

app = FastAPI(
    title="Getnet AI Agent",
    description="API para o sistema multiagente de suporte.",
    version="0.3.0",
)

registry = register_customer_tools(tool_registry)
missing_tools = [
    name for name in ("lookup_customer", "lookup_transaction", "lookup_settlement")
    if registry.get(name) is None
]
if missing_tools:
    raise RuntimeError(f"Required customer support tools are missing from the registry: {missing_tools}")

orchestrator = ChatOrchestrator(registry=registry)
session_memory = SessionMemory()
handoff_store = HumanHandoffStore()
bearer_scheme = HTTPBearer(auto_error=False)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    session_id: str | None = None


class ChatResponse(BaseModel):
    user_id: str
    message: str
    response: str
    agent: str
    routing_reason: str
    request_id: str
    total_latency_ms: int = 0
    sources: list[str] = Field(default_factory=list)
    source_sections: dict[str, list[str]] = Field(default_factory=dict)
    tool_used: str | None = None
    flow_completed: bool = False
    response_delivered: bool = False
    issue_resolved: bool = False
    resolved: bool = False
    handoff_required: bool = False
    awaiting_user_input: bool = False
    step_status: str = "success"
    handoff: dict | None = None
    verified_facts: list[dict] = Field(default_factory=list)
    fact_conflicts: list[dict] = Field(default_factory=list)
    trace: list[dict] = Field(default_factory=list)


@app.get("/health")
def health_check():
    return {"status": "ok"}


def _serialize_ticket_for_actor(record: dict, actor_user_id: str) -> dict:
    return handoff_store.serialize_for_user(record, actor_user_id)


@app.get("/human-handoff")
def list_handoffs(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    actor_user_id = authenticate_user(credentials)
    records = handoff_store.list_for_user(actor_user_id)
    return [_serialize_ticket_for_actor(record, actor_user_id) for record in records]


@app.get("/human-handoff/{ticket_id}")
def get_handoff(
    ticket_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    actor_user_id = authenticate_user(credentials)
    record = handoff_store.get(ticket_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket não encontrado.")
    if not (is_attendant_user(actor_user_id) or record["user_id"] == actor_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você não tem permissão para acessar este ticket.")
    return _serialize_ticket_for_actor(record, actor_user_id)


@app.post("/human-handoff/{ticket_id}/assume")
def assume_handoff(
    ticket_id: str,
    payload: dict,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    actor_user_id = authenticate_user(credentials)
    if not is_attendant_user(actor_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas atendentes podem assumir tickets.")

    assignee = payload.get("assignee") if isinstance(payload, dict) else None
    if assignee is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="assignee é obrigatório.")
    if assignee != actor_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Você só pode assumir tickets para si mesmo.")

    try:
        record = handoff_store.assume(ticket_id, assignee or "")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return record


@app.post("/human-handoff/{ticket_id}/complete")
def complete_handoff(
    ticket_id: str,
    payload: dict,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    actor_user_id = authenticate_user(credentials)
    if not is_attendant_user(actor_user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Apenas atendentes podem concluir tickets.")

    resolution = payload.get("resolution") if isinstance(payload, dict) else None
    try:
        record = handoff_store.complete(ticket_id, resolution or "")
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return record


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    request_id = uuid.uuid4().hex
    started_at = time.perf_counter()
    authenticated_user_id = authenticate_user(credentials)

    if not hmac.compare_digest(authenticated_user_id, request.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O usuário informado não corresponde à identidade autenticada.",
        )

    # Nunca registrar o conteúdo da mensagem: pode conter dados pessoais.
    logger.info("chat_request_received request_id=%s", request_id)

    session_key = request.session_id or authenticated_user_id
    active_handoff = handoff_store.find_active_for_session(
        user_id=authenticated_user_id,
        session_id=session_key,
    )

    if active_handoff and (
        "status" in request.message.lower() or "atendimento humano" in request.message.lower()
    ):
        status_text = {
            "pending": "pendente",
            "assigned": "assumido",
        }.get(active_handoff["status"], active_handoff["status"])
        result = {
            "agent": "human_escalation",
            "response": (
                f"Seu atendimento humano está {status_text}. "
                f"Ticket: {active_handoff['id']}."
            ),
            "sources": [],
            "source_sections": {},
            "tool_used": "human_escalation",
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "resolved": False,
            "handoff_required": True,
            "awaiting_user_input": False,
            "step_status": "handoff",
            "handoff": active_handoff,
        }
        decision = RoutingDecision(
            agent="human_escalation",
            reason="The request is checking the lifecycle of an active human handoff.",
        )
        trace = []
        total_latency_ms = int((time.perf_counter() - started_at) * 1000)
        response = ChatResponse(
            user_id=authenticated_user_id,
            message=request.message,
            response=result["response"],
            agent=result["agent"],
            routing_reason=decision.reason,
            request_id=request_id,
            total_latency_ms=total_latency_ms,
            sources=result.get("sources", []),
            source_sections=result.get("source_sections", {}),
            tool_used=result.get("tool_used"),
            flow_completed=result.get("flow_completed", True),
            response_delivered=result.get("response_delivered", bool(result.get("response"))),
            issue_resolved=result.get("issue_resolved", False),
            resolved=result.get("resolved", False),
            handoff_required=result.get("handoff_required", False),
            awaiting_user_input=result.get("awaiting_user_input", False),
            step_status=result.get("step_status", "handoff"),
            handoff=result.get("handoff"),
            trace=trace,
        )
        return response

    recent_context = session_memory.get_recent_context(
        user_id=authenticated_user_id,
        session_id=session_key,
        limit=5,
    )

    contextual_reference = session_memory.resolve_contextual_reference(
        user_id=authenticated_user_id,
        session_id=session_key,
        message=request.message,
        limit=5,
    )
    routing_context = contextual_reference

    memory_direct_answer = session_memory.answer_from_context(
        user_id=authenticated_user_id,
        session_id=session_key,
        message=request.message,
    )

    if memory_direct_answer:
        # This branch is entered only when session memory produced a direct,
        # sufficient answer for the current question.
        memory_answer_sufficient = bool(memory_direct_answer.strip())
        decision = RoutingDecision(
            agent="memory",
            reason="The answer was derived from the recent session context.",
        )
        result = {
            "agent": "memory",
            "response": memory_direct_answer,
            "sources": [],
            "source_sections": {},
            "tool_used": "session_memory",
            "issue_resolved": memory_answer_sufficient,
            "resolved": memory_answer_sufficient,
            "handoff_required": False,
            "awaiting_user_input": False,
            "step_status": "success" if memory_answer_sufficient else "failed",
        }
        trace = []
    else:
        execution = orchestrator.handle(
            request.message,
            authenticated_user_id,
            request_id=request_id,
            routing_context=routing_context,
            conversation_context=recent_context,
        )
        decision = execution.decision
        result = execution.result
        trace = [
            {
                "agent": step.agent,
                "reason": step.reason,
                "status": step.status,
                "tool_used": step.tool_used,
                "request_id": step.request_id,
                "duration_ms": step.duration_ms,
            }
            for step in execution.trace
        ]

    if result.get("handoff_required") and result.get("step_status") == "handoff":
        ticket = handoff_store.create(
            user_id=authenticated_user_id,
            session_id=session_key,
            message=request.message,
        )
        result["handoff"] = ticket
        result["flow_completed"] = True
        result["response_delivered"] = bool(result.get("response"))
        result["issue_resolved"] = False
        result["resolved"] = False
        result["awaiting_user_input"] = False
        result["step_status"] = "handoff"
    else:
        result["flow_completed"] = True
        result["response_delivered"] = bool(result.get("response"))
        result["awaiting_user_input"] = bool(result.get("awaiting_user_input", False))
        result["issue_resolved"] = bool(result.get("issue_resolved", False))
        result["resolved"] = result["issue_resolved"]

        if result.get("step_status") is None:
            if result["awaiting_user_input"]:
                result["step_status"] = "waiting_for_user_input"
            elif result.get("agent") == "fallback":
                result["step_status"] = "failed"
            else:
                result["step_status"] = "success"
        else:
            result["step_status"] = result["step_status"]

    session_memory.add_message(
        user_id=authenticated_user_id,
        session_id=session_key,
        message=request.message,
        response=result.get("response", ""),
    )

    total_latency_ms = int((time.perf_counter() - started_at) * 1000)

    logger.info(
        "router_decision agent=%s reason=%s request_id=%s",
        decision.agent,
        decision.reason,
        request_id,
    )

    sanitized_verified_facts = public_verified_facts(result.get("verified_facts", []))
    sanitized_fact_conflicts = public_fact_conflicts(result.get("fact_conflicts", []))

    response = ChatResponse(
        user_id=authenticated_user_id,
        message=request.message,
        response=result["response"],
        agent=result["agent"],
        routing_reason=decision.reason,
        request_id=request_id,
        total_latency_ms=total_latency_ms,
        sources=result.get("sources", []),
        source_sections=result.get("source_sections", {}),
        tool_used=result.get("tool_used"),
        flow_completed=result.get("flow_completed", True),
        response_delivered=result.get("response_delivered", bool(result.get("response"))),
        issue_resolved=result.get("issue_resolved", False),
        resolved=result.get("resolved", result.get("issue_resolved", False)),
        handoff_required=result.get("handoff_required", False),
        awaiting_user_input=result.get("awaiting_user_input", False),
        step_status=result.get("step_status", "success"),
        handoff=result.get("handoff"),
        verified_facts=sanitized_verified_facts,
        fact_conflicts=sanitized_fact_conflicts,
        trace=trace,
    )

    logger.info(
        "chat_response agent=%s tool_used=%s handoff_required=%s request_id=%s total_latency_ms=%s",
        response.agent,
        response.tool_used,
        response.handoff_required,
        response.request_id,
        response.total_latency_ms,
    )
    return response
