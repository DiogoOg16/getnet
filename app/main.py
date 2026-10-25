import hmac
import logging

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.auth import authenticate_user
from app.orchestrator import ChatOrchestrator

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

orchestrator = ChatOrchestrator()
bearer_scheme = HTTPBearer(auto_error=False)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class ChatResponse(BaseModel):
    user_id: str
    message: str
    response: str
    agent: str
    routing_reason: str
    sources: list[str] = Field(default_factory=list)
    source_sections: dict[str, list[str]] = Field(default_factory=dict)
    tool_used: str | None = None
    handoff_required: bool = False
    trace: list[dict] = Field(default_factory=list)


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    authenticated_user_id = authenticate_user(credentials)

    if not hmac.compare_digest(authenticated_user_id, request.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O usuário informado não corresponde à identidade autenticada.",
        )

    # Nunca registrar o conteúdo da mensagem: pode conter dados pessoais.
    logger.info("chat_request_received")

    execution = orchestrator.handle(request.message, authenticated_user_id)
    decision = execution.decision
    result = execution.result

    logger.info(
        "router_decision agent=%s reason=%s",
        decision.agent,
        decision.reason,
    )

    response = ChatResponse(
        user_id=authenticated_user_id,
        message=request.message,
        response=result["response"],
        agent=result["agent"],
        routing_reason=decision.reason,
        sources=result.get("sources", []),
        source_sections=result.get("source_sections", {}),
        tool_used=result.get("tool_used"),
        handoff_required=result.get("handoff_required", False),
        trace=[
        {
            "agent": step.agent,
            "reason": step.reason,
            "status": step.status,
            "tool_used": step.tool_used,
        }
        for step in execution.trace
    ],
    )

    logger.info(
        "chat_response agent=%s tool_used=%s handoff_required=%s",
        response.agent,
        response.tool_used,
        response.handoff_required,
    )
    return response
