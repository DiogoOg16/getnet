import logging

from fastapi import FastAPI
from pydantic import BaseModel, Field

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


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    logger.info(
        "chat_request user_id=%s message=%s",
        request.user_id,
        request.message,
    )

    execution = orchestrator.handle(request.message, request.user_id)
    decision = execution.decision
    result = execution.result

    logger.info(
        "router_decision user_id=%s agent=%s reason=%s",
        request.user_id,
        decision.agent,
        decision.reason,
    )

    response = ChatResponse(
        user_id=request.user_id,
        message=request.message,
        response=result["response"],
        agent=result["agent"],
        routing_reason=decision.reason,
        sources=result.get("sources", []),
        source_sections=result.get("source_sections", {}),
        tool_used=result.get("tool_used"),
        handoff_required=result.get("handoff_required", False),
    )

    logger.info(
        "chat_response user_id=%s agent=%s tool_used=%s handoff_required=%s",
        request.user_id,
        response.agent,
        response.tool_used,
        response.handoff_required,
    )
    return response
