from dataclasses import dataclass

from app.agents.customer_support import CustomerSupportAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.router import RouterAgent
from app.agents.web_search import WebSearchAgent


@dataclass(frozen=True)
class ChatExecution:
    decision: object
    result: dict


class ChatOrchestrator:
    """Routes requests to the appropriate specialized agent and executes the flow."""

    def __init__(self) -> None:
        self.router = RouterAgent()
        self.knowledge = KnowledgeAgent()
        self.support = CustomerSupportAgent()
        self.web_search = WebSearchAgent()

    def handle(self, message: str, user_id: str) -> ChatExecution:
        decision = self.router.route(message)

        if decision.agent == "knowledge":
            result = self.knowledge.answer(message)
        elif decision.agent == "customer_support":
            result = self.support.answer(message=message, user_id=user_id)
        elif decision.agent == "web_search":
            result = self.web_search.answer(message)
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

        return ChatExecution(decision=decision, result=result)
