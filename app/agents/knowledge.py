import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import requests

from app.llm.ollama_client import OllamaClient, OllamaClientError
from app.rag.retriever import all_documents, normalize, retrieve
from app.logging_utils import log_exception
from app.observability import record_call
from app.verified_facts import PUBLIC_FACT_NAMES, _is_authorized_fact_origin, _validate_fact_value

logger = logging.getLogger("getnet_knowledge")

PLUGIN_NAMES = ("vtex", "magento", "shopify", "plugins digitais")

# Pedido de prevenção ou redução: o documento de chargeback não cobre.
CHARGEBACK_PREVENTION_TERMS = (
    "evitar", "evito", "prevenir", "previnir", "prevenção", "prevencao", "previn",
    "reduzir", "reduzo", "diminuir", "diminuo", "cuidado", "proteger", "protejo",
    "não ter", "nao ter", "não sofrer", "nao sofrer", "não receber", "nao receber",
)
# Pergunta conceitual: o que é, o que significa, quando/por que ocorre.
CHARGEBACK_CONCEPT_TERMS = (
    "o que é", "o que e ", "o que significa", "significado", "definição", "definicao",
    "quando ocorre", "quando acontece", "por que ocorre", "por que acontece",
    "em quais situações", "em quais situacoes", "motivos", "causas",
)


@dataclass(frozen=True)
class DirectAnswer:
    """Resposta fixa com os títulos do corpus que a sustentam."""

    text: str
    sources: tuple[str, ...]
    resolved: bool = True


def title_key(title: str) -> str:
    """Título comparável: sem acento, caixa, espaços especiais nem sufixo " - Getnet"."""
    text = normalize(title.replace("\u200b", "")).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*-\s*getnet$", "", text)


def documents_by_title(titles: tuple[str, ...]) -> list[dict]:
    """Documentos do corpus com esses títulos (o primeiro de cada), na ordem pedida."""
    by_key: dict[str, dict] = {}
    for document in all_documents():
        by_key.setdefault(title_key(document["title"]), document)
    return [by_key[key] for key in map(title_key, titles) if key in by_key]


_ERROR_CODE = re.compile(r"\b(adq|idl)\s*(\d)\s*-\s*(\d{2})\b|\bs\s*-\s*(\d{4})\b")


def error_codes(text: str) -> list[str]:
    """Códigos de erro de maquininha no texto, como "adq 4-83" ou "s-2074"."""
    codes = []
    for prefix, group, number, s_code in _ERROR_CODE.findall(normalize(text)):
        codes.append(f"s-{s_code}" if s_code else f"{prefix} {group}-{number}")
    return codes


@lru_cache(maxsize=1)
def error_documents() -> dict[str, dict]:
    """Páginas de erro da base ("Erro ADQ 4-83: ..."), por código."""
    documents: dict[str, dict] = {}
    for document in all_documents():
        if not normalize(document["title"]).startswith("erro "):
            continue
        codes = error_codes(document["title"].split(":")[0])
        if codes:
            documents.setdefault(codes[0], document)
    return documents


class KnowledgeAgent:
    """Answers questions using retrieved documents and a local LLM."""

    SECTION_LABELS = {
        "customer_faq": "FAQ da Getnet",
        "faq": "FAQ",
        "technical_documentation": "Documentação técnica",
        "product_page": "Produtos e soluções",
        "general": "Geral",
        "pix": "Pix",
        "plugins": "Plugins",
        "get tap": "Get Tap",
        "maquininha": "Maquininha",
        "link de pagamento": "Link de Pagamento",
        "crediario": "Crediário",
        "conciliador": "Conciliador",
        "get conta": "Get Conta",
        "antecipacao": "Antecipação",
        "gestao de vendas": "Gestão de Vendas",
    }

    def __init__(self):
        self.ollama_url = os.getenv(
            "OLLAMA_URL", "http://localhost:11434"
        )
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.client = OllamaClient(self.ollama_url, self.model)

    @classmethod
    def _group_sources_by_section(cls, sources: list[dict]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for source in sources:
            section_value = str(source.get("section") or source.get("category") or "Geral").strip()
            section_key = section_value.lower()
            section = cls.SECTION_LABELS.get(section_key, section_value)
            grouped.setdefault(section, [])
            title = source.get("title", "Documento sem título")
            if title not in grouped[section]:
                grouped[section].append(title)
        return grouped

    def _direct_answer(self, message: str, sources: list[dict]) -> DirectAnswer | None:
        """Respostas fixas para perguntas cuja resposta está num documento da base.

        Cada resposta declara o(s) título(s) do corpus que sustentam o texto; só eles
        são citados como fonte. Meta-respostas (a base não cobre o assunto) não
        citam fonte e não marcam o caso como resolvido.
        """
        query = message.lower().strip()
        titles = [source.get("title", "").lower() for source in sources]

        if "como acesso a minha get conta" in query or "acesso a minha get conta" in query:
            return DirectAnswer(
                "Para acessar sua Get Conta, baixe o App Getnet na loja de aplicativos e faça login com o CPF/CNPJ ou e-mail e a senha cadastrada na Getnet, "
                "pelo Aplicativo Getnet Brasil ou pelo Portal Minha Conta.",
                ("Como acesso a minha Get Conta?",),
            )

        # Só a transferência da Get Conta: o limite do Pix é outro (ver "Meus Limites").
        if ("transferencia" in query or "transferência" in query) and "pix" not in query:
            if "limite" in query or "limites" in query or "diarios" in query or "diários" in query:
                return DirectAnswer(
                    "Na Get Conta, no aplicativo Getnet Brasil, vá em Transferência, preencha o valor e os dados da conta de destino e confirme a transferência. "
                    "Os limites documentados são: saque de R$ 1.000,00 por dia; transferências bancárias de R$ 2.000,00 por dia; transferências entre contas Getnet de R$ 1.000,00 por dia; e para boleto, o valor mínimo é R$ 10,00 e o máximo é R$ 1.000,00. "
                    "A operação exige saldo disponível na conta de pagamento.",
                    (
                        "Como realizo uma transferência e quais os limites diários?",
                        "Quais são os meus limites diários para realizar transações?",
                    ),
                )

        if "tarifa de inatividade" in query or "inatividade" in query:
            return DirectAnswer(
                "A tarifa de inatividade é cobrada quando a sua Get Conta permanece sem movimentações financeiras por 180 dias. "
                "Nessa situação, a cobrança é de R$ 10,00 por mês enquanto a conta estiver inativa, e o valor é descontado do saldo disponível. "
                "A conta volta a ficar ativa quando você realiza novas movimentações, como receber vendas, Pix, TED, pagamento de boleto, saque ou compras com o cartão Getnet Elo.",
                ("O que é tarifa de inatividade?", "Como saber se minha conta está inativa?"),
            )

        if "como estornar uma venda" in query or "estorno de uma venda" in query or "estornar uma venda" in query:
            return DirectAnswer(
                "Para estornar uma venda na maquininha Getnet, a documentação oficial informa: "
                "1) acesse Menu > Mastercard/Visa ou Bandeiras > Suporte > Estorno; 2) informe a senha do lojista; 3) digite o valor da venda e siga os passos para passar, inserir ou digitar o cartão; 4) informe o tipo de transação, o número CV, a data da venda e o terminal de origem; 5) aguarde a impressão do comprovante. "
                "Se a venda foi realizada em outro dia, a orientação é entrar em contato com a Central de Relacionamento Getnet.",
                ("Como realizo o estorno de uma venda?",),
            )

        if "chargeback" in query:
            text = (
                "Chargeback é a contestação de uma venda feita pelo banco quando o cliente questiona a transação: o banco cancela a transação, com débito na conta do estabelecimento. "
                "A documentação da Getnet explica que ele pode ocorrer por devolução da mercadoria, mercadoria não recebida, entrega com defeito, produto diferente do descrito, serviço não prestado adequadamente, transação não reconhecida ou não autorizada, duplicidade de transação, crédito não processado ou pagamento por meio alternativo."
            )
            # O documento define o chargeback e lista as situações em que ocorre; não
            # traz prevenção. Só a pergunta conceitual fica resolvida.
            prevention = any(term in query for term in CHARGEBACK_PREVENTION_TERMS)
            conceptual = any(term in query for term in CHARGEBACK_CONCEPT_TERMS)
            if prevention:
                text += " A base de conhecimento não traz orientações específicas de prevenção além dessas situações."
            return DirectAnswer(text, ("O que é Chargeback?",), resolved=conceptual and not prevention)

        if ("status" in query and "venda" in query) or "status das minhas vendas" in query:
            return DirectAnswer(
                "Os possíveis status das suas vendas são: 1) Pré-Autorizada; 2) Autorizada; 3) Negada; "
                "4) Desfeita; 5) Estornada; 6) Cancelada; 7) Cancelada Parcial. "
                "Para vendas com Pix, os status são: Qr Code Criado, Qr Code Expirado, Paga, Negada, Enviada ao banco e Falha no repasse.",
                ("Quais são os possíveis status das minhas vendas?", "Possíveis status das suas vendas com Pix:"),
            )

        if "pix pelo portal" in query or "habilitar o pix pelo portal" in query:
            return DirectAnswer(
                "Para habilitar o Pix pelo portal, acesse o Portal Getnet com login e senha, vá em “Vendas com Pix”, "
                "clique em “Habilitar Venda com Pix”, confirme a solicitação, aceite os termos e selecione o domicílio bancário. "
                "Depois, confirme a senha do login e acompanhe o pedido em “Produtos e Serviços” / “Meus pedidos”.",
                ("Como habilitar Pix pelo Portal?",),
            )

        if "desabilitar" in query and "pix" in query and "aplicativo" in query:
            return DirectAnswer(
                "Para desabilitar o recebimento de vendas via Pix no aplicativo Getnet Brasil: "
                "1) faça login; 2) entre em “Serviços”; 3) escolha “Pix”; 4) localize a conta habilitada; "
                "5) toque nos três pontinhos ao lado da conta; 6) escolha a opção para desabilitar o Pix e confirme.",
                ("Passo a Passo para Desabilitar o Pix",),
            )

        if "cadastro" in query or "cadastrar" in query:
            # Só chave Pix: "conta bancária para receber Pix" não é cadastro de chave.
            if "chave" in query:
                return DirectAnswer(
                    "Para cadastrar uma chave Pix na sua Get Conta, acesse o Aplicativo Getnet Brasil, vá em Conta > Pix > Minhas Chaves e selecione Cadastrar chave.",
                    ("Como cadastrar minhas chaves na minha Get Conta?",),
                )
            if "negocio" in query or "negócio" in query or "empresa" in query or "meu comercio" in query:
                return DirectAnswer(
                    "A base de conhecimento da Getnet não contém um artigo sobre o cadastro inicial de um negócio.",
                    (),
                    resolved=False,
                )

        if "biometr" in query and "pix" in query:
            return DirectAnswer(
                "O pagamento com autenticação biométrica acontece em dois momentos: na vinculação inicial, o cliente vincula a conta ao app ou ao site, gera as chaves e define biometria ou PIN; nas compras seguintes, o pagamento é iniciado no app ou site, o cliente não precisa abrir o banco, a autenticação biométrica acontece localmente e o banco valida a transação em tempo real via Pix, com confirmação imediata.",
                (
                    "Como será o pagamento biométrico via Pix?",
                    "1. Vinculação da conta (primeiro uso)",
                    "2. Iniciação e autenticação dos pagamentos (usuários recorrentes)",
                ),
            )

        if "get tap" in query and "pix" in query and ("habilitar" in query or "vender" in query):
            return DirectAnswer(
                "Para habilitar e vender via Pix usando o Get Tap, primeiro acesse o aplicativo Getnet Brasil e faça login; "
                "entre em “Serviços”, selecione “Venda com Pix” e clique em “Habilitar”; escolha o banco para vincular a conta; "
                "com o Pix habilitado, abra o Get Tap, selecione a opção de venda e escolha Pix por QR Code ou aproximação.",
                ("Como habilitar e vender via Pix pelo Get Tap", "Como vender via Pix por aproximação pelo Get Tap?"),
            )

        if "qr code" in query and "pix" in query:
            for title in titles:
                if "vender via pix" in title or "venda com pix" in title or "pix na maquininha" in title:
                    return DirectAnswer(
                        "Para vender via Pix por QR Code na maquininha: 1) inicie a máquina e selecione “Pagamento”; 2) digite o valor e prossiga; 3) escolha a opção Pix; 4) quando aparecer o QR Code, peça para o cliente ler o código no app bancário ou carteira digital; 5) finalize a transação e aguarde a confirmação da venda.",
                        ("Se já estiver habilitado siga o passo a passo:",),
                    )

        if "plugin" in query or "plugins" in query:
            if any(term in query for term in ("vtex", "magento", "shopify")) or any(term in " ".join(titles) for term in PLUGIN_NAMES):
                return DirectAnswer(
                    "A Getnet trabalha com plugins digitais de várias plataformas, como VTEX, Magento, WooCommerce e Shopify. "
                    "As funcionalidades variam por plugin; no VTEX, por exemplo: API V1 e API V2, crédito à vista e parcelado, boleto, Pix, antifraude, cancelamento e estorno, softdescriptor e confirmação tardia.",
                    ("1. VTEX", "2. MAGENTO", "3. WOOCOMMERCE", "8. SHOPIFY"),
                )

        if "erro" in query:
            return self._error_code_answer(query)

        return None

    @staticmethod
    def _error_code_answer(query: str) -> DirectAnswer | None:
        """Significado de um código de erro, só a partir dos títulos da base.

        As páginas de erro foram ingeridas sem os passos de solução (o conteúdo para
        em "siga as instruções abaixo"), então a resposta dá o significado e não
        marca o caso como resolvido. Código fora da base: a resposta diz isso, e o
        Customer Support encaminha ao atendimento.
        """
        codes = error_codes(query)
        if not codes:
            return None
        documents = error_documents()
        for code in codes:
            if code in documents:
                document = documents[code]
                meaning = document["title"].split(" - Getnet")[0].strip()
                return DirectAnswer(
                    f"{meaning}. A base de conhecimento da Getnet identifica esse código, mas não traz o passo a passo de solução.",
                    (document["title"],),
                    resolved=False,
                )
        return DirectAnswer(
            f"Não encontrei informações sobre o código {codes[0].upper()} na base de conhecimento da Getnet.",
            (),
            resolved=False,
        )

    @staticmethod
    def _normalize_for_match(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @classmethod
    def _find_passage(cls, content: str, term: str) -> str | None:
        """Texto do item do documento que define `term` (item "• Termo: ...").

        O documento de status das vendas lista cada status como um item
        iniciado por "•"; devolve o item cujo rótulo é `term`, com as mesmas
        palavras e pontuação, sem o marcador "•" e com espaços e quebras de
        linha normalizados para um espaço.
        """
        wanted = cls._normalize_for_match(term).strip()
        for item in content.split("•"):
            passage = " ".join(item.split())
            label = passage.split(":", 1)[0]
            if ":" in passage and cls._normalize_for_match(label).strip() == wanted:
                return passage
        return None

    def quote(self, query: str, term: str) -> dict:
        """Responde citando o texto da base que define `term` (ver _find_passage).

        Usado quando a explicação precisa ser fiel à fonte (ARCH-02 / P2): não há
        geração por LLM, então nenhuma causa ou detalhe fora do documento pode
        ser acrescentado. Se nenhum documento recuperado define o termo, a etapa
        não improvisa: diz que a documentação não traz a definição, marca
        step_status = "no_evidence" e registra um aviso no log.
        """
        with record_call("retrieval", "bm25"):
            sources = retrieve(query)
        for source in sources:
            passage = self._find_passage(source.get("content", ""), term)
            if passage:
                title = " ".join(source.get("title", "").split())
                return {
                    "agent": "knowledge",
                    "response": f"“{passage}” (Fonte: {title})",
                    "sources": [source.get("title", "")],
                    "tool_used": "retrieval_quote",
                    "flow_completed": True,
                    "response_delivered": True,
                    "issue_resolved": False,
                    "resolved": False,
                    "awaiting_user_input": False,
                    "step_status": "success",
                    "source_sections": self._group_sources_by_section([source]),
                }
        logger.warning(
            "knowledge_quote_not_found term=%s retrieved=%s", term, len(sources)
        )
        return {
            "agent": "knowledge",
            "response": (
                "A documentação recuperada não traz a definição desse status, "
                "então não há trecho para citar."
            ),
            "sources": [],
            "tool_used": "retrieval_quote",
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "resolved": False,
            "awaiting_user_input": False,
            "step_status": "no_evidence",
            "source_sections": {},
        }

    @staticmethod
    def _extractive_answer(sources: list[dict], max_chars: int = 600) -> str:
        """Resposta sem LLM: trechos recuperados, com título e limite de tamanho."""
        parts = []
        for source in sources:
            content = source["content"].strip()
            if len(content) > max_chars:
                content = content[:max_chars].rsplit(" ", 1)[0] + "…"
            parts.append(f"• {source['title']}: {content}")
        return (
            "O modelo de linguagem não está disponível agora, então seguem "
            "os trechos mais relevantes da base de conhecimento da Getnet:\n\n"
            + "\n\n".join(parts)
        )

    def _generate(self, message: str, context: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Você é um agente de suporte da Getnet. "
                    "Responda em português brasileiro, de forma "
                    "clara e direta. Use somente as informações "
                    "do contexto fornecido. Não invente regras, "
                    "taxas, procedimentos ou funcionalidades. "
                    "Se o contexto não responder à pergunta, "
                    "diga que não há informação suficiente."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Pergunta: {message}\n\n"
                    f"Contexto da base de conhecimento:\n{context}"
                ),
            },
        ]
        response = self.client.chat(messages)
        return self.client.parse_message_content(response)

    @staticmethod
    def _verified_fact_context(verified_facts: list[dict] | None) -> str:
        if not verified_facts:
            return ""

        lines = [
            "Fatos operacionais verificados na execução atual:",
        ]
        for fact in verified_facts:
            if not isinstance(fact, dict):
                continue
            if fact.get("verified") is not True:
                continue
            if not _is_authorized_fact_origin(fact):
                continue
            if fact.get("source_agent") != "customer_support":
                continue
            name = str(fact.get("name", "")).strip()
            if name not in PUBLIC_FACT_NAMES:
                continue
            source_tool = str(fact.get("source_tool", "")).strip()
            if not source_tool:
                continue
            if _validate_fact_value(name, fact.get("value")) is None:
                continue
            lines.append(
                f"- entidade={fact.get('entity')} nome={name} "
                f"valor={fact.get('value')} origem={source_tool}"
            )
        return "\n".join(lines) if len(lines) > 1 else ""

    def answer(
        self,
        message: str,
        verified_facts: list[dict] | None = None,
        generation_context: str = "",
    ) -> dict:
        query = message.lower().strip()
        fact_context = self._verified_fact_context(verified_facts)

        if "configurar" in query and "wi" in query and "maquininha" in query:
            return {
                "agent": "knowledge",
                "response": (
                    "A base de conhecimento da Getnet não contém o procedimento de configuração de Wi-Fi para cada modelo de maquininha, "
                    "e por isso não há instruções suficientes para orientar essa configuração."
                ),
                "sources": [],
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": False,
                "resolved": False,
                "awaiting_user_input": False,
                "step_status": "success",
                "source_sections": {},
            }

        with record_call("retrieval", "bm25"):
            sources = retrieve(message)

        if not sources:
            return {
                "agent": "knowledge",
                "response": (
                    "Não encontrei informações suficientes na base de "
                    "conhecimento para responder com segurança. Consulte "
                    "a documentação oficial da Getnet ou o atendimento."
                ),
                "sources": [],
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": False,
                "resolved": False,
                "awaiting_user_input": False,
                "step_status": "failed",
                "source_sections": {},
            }

        direct_answer = self._direct_answer(message, sources)
        backing = documents_by_title(direct_answer.sources) if direct_answer else []
        if direct_answer and len(backing) != len(direct_answer.sources):
            # Fonte declarada que não está na base: a resposta fixa não é entregue,
            # e a pergunta segue o fluxo normal (LLM com os documentos recuperados).
            logger.warning(
                "knowledge_direct_answer_source_missing declared=%s found=%s",
                len(direct_answer.sources), len(backing),
            )
            direct_answer = None
        if direct_answer:
            # Cita só os documentos que sustentam o texto, não os 3 recuperados.
            return {
                "agent": "knowledge",
                "response": direct_answer.text,
                "sources": [source["title"] for source in backing],
                "flow_completed": True,
                "response_delivered": True,
                "issue_resolved": direct_answer.resolved,
                "resolved": direct_answer.resolved,
                "awaiting_user_input": False,
                "step_status": "success",
                "source_sections": self._group_sources_by_section(backing),
            }

        context_parts = [
            f"Documento: {source['title']}\nConteúdo: {source['content']}"
            for source in sources
        ]
        if fact_context:
            context_parts.insert(0, fact_context)
        if generation_context:
            context_parts.append(
                "Histórico recente da conversa (use somente para entender "
                "referências da pergunta; não é fonte de fatos):\n"
                f"{generation_context}"
            )

        context = "\n\n".join(context_parts)

        try:
            answer = self._generate(message, context)
            tool_used = "ollama"
        except (requests.RequestException, OllamaClientError, ValueError, KeyError) as exc:
            log_exception(logger, "knowledge_generation_fallback", exc, level=logging.WARNING)
            answer = self._extractive_answer(sources)
            tool_used = "retrieval_only"

        return {
            "agent": "knowledge",
            "response": answer,
            "tool_used": tool_used,
            "sources": [source["title"] for source in sources],
            "flow_completed": True,
            "response_delivered": True,
            "issue_resolved": False,
            "resolved": False,
            "awaiting_user_input": False,
            "step_status": "success",
            "source_sections": self._group_sources_by_section(sources),
        }