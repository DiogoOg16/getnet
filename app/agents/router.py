from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class RoutingDecision:
    agent: str
    reason: str


def normalize(text: str) -> str:
    text = unicodedata.normalize(
        "NFKD", text.replace("’", "'").casefold()
    )
    return "".join(
        char for char in text
        if not unicodedata.combining(char)
    ).strip()


def _compile(patterns: tuple[str, ...]) -> re.Pattern:
    return re.compile("|".join(patterns))


# Todos os padrões operam sobre texto normalizado (minúsculo, sem acentos).

TRANSACTION_ID = re.compile(r"\btxn\d+\b")

DEVICE = _compile((
    r"\bmaquin",
    r"\bcard machine\b",
    r"\bcard reader\b",
    r"\bterminal\b",
))

DEVICE_PROBLEM = _compile((
    r"\bnao conecta",
    r"\bnao liga",
    r"\bnao funciona",
    r"\btravou",
    r"\binternet\b",
    r"\bwi-?fi\b",
    r"\berro\b",
    r"\berror\b",
    r"\bdeclin",
    r"\brecus",
    r"\bwon'?t\b",
    r"\bnot working\b",
    r"\bconnect",
    r"\bfreez",
))

SUPPORT = _compile((
    r"\bminha conta\b",
    r"\bmeu cadastro\b",
    r"\bmeus dados\b",
    r"\bmeu perfil\b",
    r"\bmeu saldo\b",
    r"\bmeu dinheiro\b",
    r"\bmeu recebimento\b",
    r"\bdeposit",
    r"\btransac",
    r"\bnao recebi\b",
    r"\bfoi recusad[ao]\b",
    r"\bnao consigo acessar\b",
    r"\bproblemas? (?:na minha conta|para acessar)\b",
    r"\bmy account\b",
    r"\bmy balance\b",
    r"\bmy money\b",
    r"\bmy payment",
    r"\bmy profile\b",
    r"\bdid(?:n't| not) receive\b",
    r"\bnot received\b",
    r"\bhaven't received\b",
))

WEB = _compile((
    r"\bclima\b",
    r"\btempo em\b",
    r"\bprevisao do tempo\b",
    r"\bweather\b",
    r"\bforecast\b",
    r"\bcotacao\b",
    r"\bcambio\b",
    r"\bexchange rate\b",
    r"\beuros?\b",
    r"\bdolar(?:es)?\b",
    r"\bdollars?\b",
    r"\bnoticias?\b",
    r"\bnews\b",
    r"\beleicao\b",
    r"\belection\b",
    r"\bquem ganhou\b",
    r"\bultimo resultado\b",
    r"\batualizado hoje\b",
))

GENERAL_CONCEPT = _compile((
    r"\bo que e\b",
    r"\bwhat is\b",
    r"\bdefinicao\b",
    r"\bdefinition\b",
))

HUMAN_ESCALATION = _compile((
    r"\b(?:dados? pessoais|informacoes? pessoais|dados sensiveis)\b",
    r"\b(?:sensivel|sensíveis|sensitive)\b",
    r"\b(?:atendimento humano|falar com humano|contato humano)\b",
    r"\b(?:nao consigo continuar|nao posso continuar|preciso de ajuda urgente)\b",
    r"\b(?:cpf|rg|senha|cartao|numero do cartao|chave pix)\b",
    r"\b(?:my personal data|sensitive data|human agent|talk to a human)\b",
))

KNOWLEDGE = _compile((
    r"\bqual a diferenca\b",
    r"\bdiferenca entre\b",
    r"\bdifference between\b",
    r"\bcomo funciona",
    r"\bhow (?:does|do i|do you|can i)\b",
    r"\bo que (?:e|sao)\b",
    r"\bwhat is\b",
    r"\bquais sao\b",
    r"\bmaquin",
    r"\bcard machine\b",
    r"\bpix\b",
    r"\bantecip",
    r"\breceivable",
    r"\blink de pagamento\b",
    r"\bpayment link\b",
    r"\bcrediario\b",
    r"\binstallment",
    r"\bparcel",
    r"\btaxas?\b",
    r"\bfees?\b",
    r"\bprodutos?\b",
    r"\bservicos?\b",
    r"\bgetnet\b",
    r"\bget (?:classica|smart)\b",
    r"\bwhatsapp\b",
))


class RouterAgent:
    """Routes incoming messages using explicit, rule-based intent patterns."""

    def route(self, message: str) -> RoutingDecision:
        text = normalize(message)

        if HUMAN_ESCALATION.search(text):
            return RoutingDecision(
                agent="human_escalation",
                reason=(
                    "The request is sensitive, unsupported, or requires human assistance."
                ),
            )

        if TRANSACTION_ID.search(text):
            return RoutingDecision(
                agent="customer_support",
                reason="The message references a specific transaction ID.",
            )

        if DEVICE.search(text) and DEVICE_PROBLEM.search(text):
            return RoutingDecision(
                agent="knowledge",
                reason=(
                    "The message describes a card machine problem; "
                    "answered from troubleshooting knowledge."
                ),
            )

        if SUPPORT.search(text):
            return RoutingDecision(
                agent="customer_support",
                reason="The message appears to concern a customer account or transaction.",
            )

        if GENERAL_CONCEPT.search(text) and not re.search(
            r"\b(?:habilitar|desabilitar|vender|configur|antecip|status|recus|consultar|pagamento|pix no|portal|get tap|getnet)\b",
            text,
        ):
            return RoutingDecision(
                agent="web_search",
                reason="The message is a general concept question, not a Getnet-specific procedure.",
            )

        if WEB.search(text):
            return RoutingDecision(
                agent="web_search",
                reason="The message appears to require external or current information.",
            )

        if KNOWLEDGE.search(text):
            return RoutingDecision(
                agent="knowledge",
                reason="The message appears to ask about a Getnet product or service.",
            )

        return RoutingDecision(
            agent="fallback",
            reason="The message intent could not be identified by the current rules.",
        )
