from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    reason: str


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(
        char for char in text
        if not unicodedata.combining(char)
    ).strip()


class RouterAgent:
    """Routes incoming messages using explicit keyword rules."""

    SUPPORT_KEYWORDS = (
        "minha venda", "minhas vendas",
        "meu pagamento", "meus pagamentos",
        "meu dinheiro", "minha conta", "meu cadastro",
        "meu recebimento", "meu saldo", "saldo",
        "deposito", "transacao", "transacoes",
        "nao consigo acessar", "nao conecta",
        "nao funciona", "foi recusada", "foi recusado",
        "nao recebi", "problema na minha conta",
        "problemas para acessar",
    )

    WEB_KEYWORDS = (
        "clima", "tempo em ", "previsao do tempo",
        "cotacao", "cambio", "euro", "dolar",
        "eleicao", "noticias", "noticia",
        "quem ganhou", "ultimo resultado",
        "atualizado hoje",
    )

    KNOWLEDGE_KEYWORDS = (
        "qual a diferenca", "como funciona",
        "o que e", "o que sao", "quais sao",
        "maquininha", "maquina de cartao",
        "pix", "antecipacao", "link de pagamento",
        "crediario", "taxas", "produtos", "servicos",
    )

    def route(self, message: str) -> RoutingDecision:
        text = normalize(message)

        if any(keyword in text for keyword in self.SUPPORT_KEYWORDS):
            return RoutingDecision(
                agent="customer_support",
                reason="The message appears to concern a customer account or transaction.",
            )

        if any(keyword in text for keyword in self.WEB_KEYWORDS):
            return RoutingDecision(
                agent="web_search",
                reason="The message appears to require external or current information.",
            )

        if any(keyword in text for keyword in self.KNOWLEDGE_KEYWORDS):
            return RoutingDecision(
                agent="knowledge",
                reason="The message appears to ask about a Getnet product or service.",
            )

        return RoutingDecision(
            agent="fallback",
            reason="The message intent could not be identified by the current rules.",
        )
