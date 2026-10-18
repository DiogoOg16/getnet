from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    reason: str


class RouterAgent:
    """Classifica mensagens e escolhe o agente responsável."""

    SUPPORT_KEYWORDS = (
        "minha venda",
        "minhas vendas",
        "meu pagamento",
        "meus pagamentos",
        "meu dinheiro",
        "minha conta",
        "meu cadastro",
        "meu recebimento",
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
        "erro na minha",
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
                reason="A mensagem parece tratar de uma conta ou operação do cliente.",
            )

        if any(keyword in text for keyword in self.KNOWLEDGE_KEYWORDS):
            return RoutingDecision(
                agent="knowledge",
                reason="A mensagem parece pedir informações sobre produtos ou serviços.",
            )

        return RoutingDecision(
            agent="fallback",
            reason="Não foi possível identificar a intenção com confiança.",
        )
