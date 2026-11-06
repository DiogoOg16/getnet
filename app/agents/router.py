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

DEVICE_OPERATIONAL_FAILURE = _compile((
    r"\bnao conecta",
    r"\bnao liga",
    r"\bnao funciona",
    r"\bcai toda hora",
    r"\bconexao instavel",
    r"\bdesconecta",
    r"\bsem internet",
    r"\btravou",
    r"\berro\b",
    r"\berror\b",
    r"\bdeclin",
    r"\brecus",
    r"\bwon'?t\b",
    r"\bcan'?t\b",
    r"\bnot working\b",
    r"\bcannot connect\b",
    r"\bfreez",
))

DEVICE_PROCEDURAL = _compile((
    r"\bconfigur",
    r"\btrocar",
    r"\bcomo usar",
    r"\bhow to use",
    r"\bhabilitar",
    r"\bsetup",
    r"\brede wi-?fi\b",
))

SUPPORT = _compile((
    r"\bminha conta\b",
    r"\bmeu cadastro\b",
    r"\bmeus dados\b",
    r"\bmeu perfil\b",
    r"\bmeu saldo\b",
    r"\bmeu dinheiro\b",
    r"\bmeu recebimento\b",
    r"\bmeu pagamento\b",
    r"\b(?:cade|cadê)\b",
    r"\b(?:nao|não) entrou\b",
    r"\b(?:dinheiro|pagamento|recebimento) (?:das vendas|da venda|de ontem)\b",
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
    # pedido explícito de atendimento humano
    r"\batendimento humano\b",
    r"\bfalar com (?:um |uma )?(?:humano|atendente|pessoa)\b",
    r"\bcontato humano\b",
    r"\bhuman agent\b",
    r"\btalk to (?:a )?(?:human|person|agent)\b",
    # usuário sem condições de continuar
    r"\bnao (?:consigo|posso) (?:continuar|prosseguir)\b",
    r"\bajuda urgente\b",
    # pedido envolvendo dados pessoais sensíveis do próprio usuário
    r"\bdados pessoais sensiveis\b",
    r"\bmy (?:personal|sensitive) data\b",
    # guardrail: dado sensível colado na mensagem (CPF ou número de cartão)
    r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b",
    r"\b(?:\d[ -]?){13,19}\b",
))

KNOWLEDGE = _compile((
    r"\bqual a diferenca\b",
    r"\bdiferenca entre\b",
    r"\bdifference between\b",
    r"\bcomo funciona",
    r"\bcomo resolver\b",
    r"\bcomo resolv",
    r"\bestorn",
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


# Continuidade de um fluxo de suporte que aguarda detalhes do usuário.
FOLLOWUP_CONTINUATION = _compile((
    r"\bcontinua\b",
    r"\bsegue (?:igual|sem|com)\b",
    r"\bmesm[ao] (?:coisa|problema|erro)\b",
    r"\breinici",
    r"\bja tentei\b",
    r"\bstill\b",
    r"\bsame (?:issue|problem|error|thing)\b",
    r"\brestart",
    r"\breboot",
    r"\balready tried\b",
))

# Negações mudam o sentido: "não resolveu" é continuidade, "resolveu" é encerramento.
FOLLOWUP_NEGATED_RESOLUTION = _compile((
    r"\bnao (?:\w+ )?(?:resolv\w*|funcion\w*|conect\w*|voltou\w*|deu certo|consegui\w*)",
    r"\b(?:didn'?t|doesn'?t|not|hasn'?t|isn'?t) (?:\w+ )?(?:work\w*|help\w*|fix\w*|solv\w*|resolv\w*|connect\w*)",
))

FOLLOWUP_RESOLUTION = _compile((
    r"\bresolv\w*",
    r"\bfuncion(?:ou|ando)\b",
    r"\bvoltou a (?:funcionar|conectar|ligar)\b",
    r"\bvoltou ao normal\b",
    r"\b(?:internet|sinal|rede|conexao|wi-?fi) voltou\b",
    r"\bconect(?:ou|ando)\b",
    r"\bdeu certo\b",
    r"\bconsegui\b",
    r"\b(?:solved|resolved|fixed)\b",
    r"\bworking (?:now|again)\b",
    r"\bworks now\b",
    r"\bback online\b",
    r"\bconnected\b",
))

FOLLOWUP_CONNECTIVITY = _compile((
    r"\bwi-?fi\b",
    r"\brede\b",
    r"\bsinal\b",
    r"\binternet\b",
    r"\bchip\b",
    r"\bconect",
    r"\bconexao\b",
    r"\bnetwork\b",
    r"\bsignal\b",
    r"\bconnect",
    r"\bmaquin",
    r"\bterminal\b",
    r"\bcard machine\b",
))

FOLLOWUP_GENERIC_DETAIL = _compile((
    r"\btela\b",
    r"\berro\b",
    r"\bmensagem\b",
    r"\bscreen\b",
    r"\berror\b",
))

# Assunto próprio: sem sinal de conectividade, não pertence ao fluxo pendente.
FOLLOWUP_OTHER_TOPIC = _compile((
    r"\bsaldo\b",
    r"\bpagamento",
    r"\bdinheiro\b",
    r"\bdeposit",
    r"\brecebiment",
    r"\btaxas?\b",
    r"\bpix\b",
    r"\bantecip",
    r"\blink\b",
    r"\bcrediario\b",
    r"\bparcel",
    r"\bconta\b",
    r"\bcadastro\b",
    r"\btransac",
    r"\bvendas?\b",
    r"\bbalance\b",
    r"\bpayment",
    r"\bfees?\b",
    r"\baccount\b",
    r"\bsales?\b",
))


class RouterAgent:
    """Routes incoming messages using explicit, rule-based intent patterns."""

    @staticmethod
    def continues_pending_flow(decision: RoutingDecision, message: str) -> bool:
        """Decide se a mensagem atual continua um fluxo pendente.

        Uma intenção nova e explícita sempre vence a continuidade.
        """
        text = normalize(message)
        if TRANSACTION_ID.search(text):
            return False

        negated = bool(FOLLOWUP_NEGATED_RESOLUTION.search(text))
        if FOLLOWUP_RESOLUTION.search(FOLLOWUP_NEGATED_RESOLUTION.sub(" ", text)):
            return False

        is_fallback = decision.agent == "fallback"
        if not is_fallback and (
            decision.agent not in {"knowledge", "customer_support"} or "?" in text
        ):
            return False

        continuation = negated or bool(FOLLOWUP_CONTINUATION.search(text))
        if FOLLOWUP_CONNECTIVITY.search(text):
            return is_fallback or continuation
        if FOLLOWUP_OTHER_TOPIC.search(text):
            return False
        return continuation or (
            is_fallback and bool(FOLLOWUP_GENERIC_DETAIL.search(text))
        )

    @staticmethod
    def _is_short_reference(message: str) -> bool:
        text = normalize(message)
        text = " ".join(filter(None, re.sub(r"[^a-z0-9\s]", " ", text).split()))
        return text in {
            "essa",
            "isso",
            "este",
            "esta",
            "aquele",
            "aquela",
            "aquilo",
            "e essa",
            "e isso",
            "e este",
            "e esta",
            "e aquele",
            "e aquela",
        }

    def route(
        self,
        message: str,
        routing_context: str | None = None,
    ) -> RoutingDecision:
        text = normalize(message)
        contextual_text = (
            normalize(f"{routing_context} {message}")
            if routing_context
            else text
        )

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

        if DEVICE.search(text):
            if re.search(
                r"\b(?:declin|recus|transaction decline|"
                r"transacao recusad[ao])",
                text,
            ):
                return RoutingDecision(
                    agent="customer_support",
                    reason=(
                        "The message reports a declined transaction "
                        "and requires operational support."
                    ),
                )

            if DEVICE_OPERATIONAL_FAILURE.search(text):
                return RoutingDecision(
                    agent="customer_support",
                    reason=(
                        "The message describes an operational card machine "
                        "failure and requires support diagnostics."
                    ),
                )

            if DEVICE_PROCEDURAL.search(text):
                return RoutingDecision(
                    agent="knowledge",
                    reason=(
                        "The message requests procedural card machine guidance "
                        "that can be answered from documented knowledge."
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

        if routing_context and self._is_short_reference(text):
            if TRANSACTION_ID.search(contextual_text):
                return RoutingDecision(
                    agent="customer_support",
                    reason="The message is a short contextual reference to a recent transaction.",
                )
            if SUPPORT.search(contextual_text):
                return RoutingDecision(
                    agent="customer_support",
                    reason="The message uses recent support context to clarify the current request.",
                )
            if DEVICE.search(contextual_text):
                return RoutingDecision(
                    agent="knowledge",
                    reason="The message references a recent device topic and should use the related support context.",
                )
            if KNOWLEDGE.search(contextual_text):
                return RoutingDecision(
                    agent="knowledge",
                    reason="The message references a recent Getnet topic and should use that contextual intent.",
                )

        return RoutingDecision(
            agent="fallback",
            reason="The message intent could not be identified by the current rules.",
        )
