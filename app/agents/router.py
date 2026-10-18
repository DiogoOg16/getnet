from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    reason: str


class RouterAgent:
    """Routes incoming messages to the appropriate agent."""

    SUPPORT_KEYWORDS = (
        "minha venda",
        "minhas vendas",
        "meu pagamento",
        "meus pagamentos",
        "meu dinheiro",
        "minha conta",
        "meu cadastro",
        "meu recebimento",
        "meu saldo",
        "saldo",
        "depósito",
        "deposito",
        "transação",
        "transacao",
        "transações",
        "transacoes",
        "não consigo acessar",
        "nao consigo acessar",
        "não conecta",
        "nao conecta",
        "não funciona",
        "nao funciona",
        "foi recusada",
        "foi recusado",
        "não recebi",
        "nao recebi",
    )

    KNOWLEDGE_KEYWORDS = (
        "qual a diferença",
        "qual é a diferença",
        "como funciona",
        "o que é",
        "o que são",
        "quais são",
        "quais sao",
        "maquininha",
        "máquina de cartão",
        "maquina de cartao",
        "pix",
        "antecipação",
        "antecipacao",
        "link de pagamento",
        "crediário",
        "crediario",
        "taxas",
        "produtos",
        "serviços",
        "servicos",
    )

    def route(self, message: str) -> RoutingDecision:
        text = message.casefold().strip()

        if any(keyword in text for keyword in self.SUPPORT_KEYWORDS):
            return RoutingDecision(
                agent="customer_support",
                reason="The message appears to concern a customer account or transaction.",
            )

        if any(keyword in text for keyword in self.KNOWLEDGE_KEYWORDS):
            return RoutingDecision(
                agent="knowledge",
                reason="The message appears to ask about a product or service.",
            )

        return RoutingDecision(
            agent="fallback",
            reason="The message intent could not be identified by the current rules.",
        )
