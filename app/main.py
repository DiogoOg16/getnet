from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.agents.router import RouterAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.customer_support import CustomerSupportAgent
from app.agents.web_search import WebSearchAgent


app = FastAPI(
    title="Getnet AI Agent",
    description="API para o sistema multiagente de suporte.",
    version="0.3.0",
)

router_agent = RouterAgent()
knowledge_agent = KnowledgeAgent()
support_agent = CustomerSupportAgent()
web_search_agent = WebSearchAgent()


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
    decision = router_agent.route(request.message)

    if decision.agent == "knowledge":
        result = knowledge_agent.answer(request.message)

    elif decision.agent == "customer_support":
        result = support_agent.answer(
            message=request.message,
            user_id=request.user_id,
        )

    elif decision.agent == "web_search":
        result = web_search_agent.answer(request.message)

    elif decision.agent == "human_escalation":
        result = {
            "agent": "human_escalation",
            "response": (
                "Solicitação fora do escopo ou sensível. "
                "Encaminho para atendimento humano para continuidade segura."
            ),
            "sources": [],
            "tool_used": "human_escalation",
            "handoff_required": True,
        }

    else:
        result = {
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
        }

    return ChatResponse(
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
