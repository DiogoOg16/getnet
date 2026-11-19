"""Respostas fixas do Knowledge: gatilhos, fontes e "resolvido" (auditoria de 2026-11-17, opção A).

Cada resposta fixa cita só o documento do corpus que sustenta o texto. Meta-respostas
(a base não cobre o assunto) não citam fonte nem marcam o caso como resolvido.
"""

import pytest

from app.agents.knowledge import (
    DirectAnswer,
    KnowledgeAgent,
    documents_by_title,
    error_codes,
    error_documents,
)
from app.rag.retriever import retrieve

# (pergunta, títulos que sustentam a resposta, resolvido)
SOURCED = [
    ("Como acesso a minha Get Conta?", ["Como acesso a minha Get Conta?"], True),
    (
        "Como realizo uma transferência e quais os limites diários?",
        [
            "Como realizo uma transferência e quais os limites diários?",
            "Quais são os meus limites diários para realizar transações?",
        ],
        True,
    ),
    (
        "O que é tarifa de inatividade?",
        ["O que é tarifa de inatividade?", "Como saber se minha conta está inativa?"],
        True,
    ),
    ("Como estornar uma venda na maquininha Getnet?", ["Como realizo o estorno de uma venda?"], True),
    ("O que é chargeback?", ["O que é Chargeback?"], True),
    ("Como evitar chargeback?", ["O que é Chargeback?"], False),
    (
        "Quais são os possíveis status das minhas vendas?",
        ["Quais são os possíveis status das minhas vendas?\xa0 - Getnet", "Possíveis status das suas vendas com Pix:"],
        True,
    ),
    ("Como habilitar o Pix pelo portal?", ["Como habilitar Pix pelo Portal​? - Getnet"], True),
    ("Como desabilitar o Pix no aplicativo?", ["Passo a Passo para Desabilitar o Pix"], True),
    ("Como cadastrar uma chave Pix?", ["Como cadastrar minhas chaves na minha Get Conta?"], True),
    (
        "Como habilitar e vender via Pix usando o Get Tap?",
        ["Como habilitar e vender via Pix pelo Get Tap", "Como vender via Pix por aproximação pelo Get Tap?"],
        True,
    ),
    ("Quais plugins a Getnet tem para VTEX e Shopify?", ["1. VTEX", "2. MAGENTO", "3. WOOCOMMERCE", "8. SHOPIFY"], True),
    (
        "Qual é o significado do erro ADQ 4-83 na maquininha?",
        ["Erro ADQ 4-83: erro de integração com as bandeiras - Getnet"],
        False,
    ),
]

# Perguntas que disparavam uma resposta fixa errada ou sem fonte.
NOT_DIRECT = [
    "Como cadastrar minha conta bancária para receber Pix?",  # R15: não é cadastro de chave
    "Qual o limite de transferência por Pix?",  # R2: limite do Pix é outro documento
    "Minha maquininha deu erro ao imprimir o comprovante",  # R21: erro genérico inventado
    "A maquininha mostra erro de senha do lojista",  # R21
    "Quero consultar minhas vendas do mês",  # R8: sem fonte
    "Funcionalidades portal minha conta e App Getnet Brasil",  # R9: sem fonte
    "Como habilitar o recebimento de vendas via pix no aplicativo Getnet Brasil?",  # R11: passos fora da base
]


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    monkeypatch.setattr(KnowledgeAgent, "_generate", lambda self, message, context: "Resposta do modelo.")


def direct(query):
    return KnowledgeAgent.__new__(KnowledgeAgent)._direct_answer(query, retrieve(query))


@pytest.mark.parametrize(("query", "titles", "resolved"), SOURCED)
def test_direct_answer_cites_only_the_documents_that_back_it(query, titles, resolved):
    result = KnowledgeAgent().answer(query)

    assert result["sources"] == titles
    assert result["resolved"] is resolved
    assert result["issue_resolved"] is resolved


@pytest.mark.parametrize(("query", "titles", "resolved"), SOURCED)
def test_every_declared_source_exists_in_the_corpus(query, titles, resolved):
    answer = direct(query)
    assert answer is not None
    assert len(documents_by_title(answer.sources)) == len(answer.sources) > 0


@pytest.mark.parametrize("query", NOT_DIRECT)
def test_wrong_or_unsourced_triggers_no_longer_fire(query):
    assert direct(query) is None


def test_qr_code_answer_cites_the_qr_code_steps():
    # Gatilho depende do título recuperado; com o retriever atual quase nunca dispara.
    sources = [{"title": "Como fazer uma venda com Pix na maquininha? - Getnet"}]
    answer = KnowledgeAgent.__new__(KnowledgeAgent)._direct_answer("Como vender via Pix por QR Code?", sources)
    assert [d["title"] for d in documents_by_title(answer.sources)] == ["Se já estiver habilitado siga o passo a passo:"]


def test_pix_limit_question_does_not_get_bank_transfer_limits():
    result = KnowledgeAgent().answer("Qual o limite de transferência por Pix?")
    assert "R$ 2.000,00" not in result["response"]


def test_chargeback_answer_has_no_unsourced_prevention_advice():
    response = KnowledgeAgent().answer("Como evitar chargeback?")["response"].lower()
    assert "manter a documentação" not in response
    assert "não traz orientações específicas de prevenção" in response


@pytest.mark.parametrize(
    "query",
    [
        "Quais cuidados devo tomar para não ter chargeback?",
        "Como reduzir os chargebacks?",
        "Como faço para não sofrer chargeback nas minhas vendas?",
        "Como me proteger de chargeback?",
        "O que é chargeback e como evitar?",
    ],
)
def test_chargeback_prevention_requests_are_not_resolved(query):
    result = KnowledgeAgent().answer(query)
    response = result["response"].lower()

    assert result["sources"] == ["O que é Chargeback?"]
    assert "não traz orientações específicas de prevenção" in response
    assert "manter a documentação" not in response
    assert result["resolved"] is False


@pytest.mark.parametrize("query", ["Chargeback na maquininha", "Tive um chargeback, e agora?"])
def test_chargeback_question_that_is_not_conceptual_is_not_resolved(query):
    result = KnowledgeAgent().answer(query)

    assert result["sources"] == ["O que é Chargeback?"]
    assert result["resolved"] is False


@pytest.mark.parametrize(
    "query",
    ["O que é chargeback?", "O que significa chargeback?", "Quando ocorre o chargeback?", "Quais os motivos de chargeback?"],
)
def test_conceptual_chargeback_question_is_resolved_without_prevention_note(query):
    result = KnowledgeAgent().answer(query)

    assert result["resolved"] is True
    assert "prevenção" not in result["response"].lower()


def test_contestacao_de_vendas_question_does_not_get_a_resolved_answer():
    # Sem a palavra "chargeback" a resposta fixa não dispara; o fluxo normal não resolve.
    result = KnowledgeAgent().answer("Como faço para não sofrer contestação de vendas?")
    assert result["resolved"] is False


def test_known_error_code_answer_gives_only_the_documented_meaning():
    result = KnowledgeAgent().answer("Qual é o significado do erro ADQ 4-30 na maquininha?")

    assert result["response"] == (
        "Erro ADQ 4-30: falha na comunicação na maquininha. "
        "A base de conhecimento da Getnet identifica esse código, mas não traz o passo a passo de solução."
    )
    assert "central de relacionamento" not in result["response"].lower()
    assert result["resolved"] is False


@pytest.mark.parametrize(
    "declared",
    [("Título que não existe na base",), ("O que é Chargeback?", "Título que não existe na base")],
)
def test_direct_answer_with_a_missing_source_is_not_delivered(monkeypatch, declared):
    monkeypatch.setattr(
        KnowledgeAgent, "_direct_answer", lambda self, message, sources: DirectAnswer("Texto fixo.", declared)
    )
    result = KnowledgeAgent().answer("O que é chargeback?")

    assert result["response"] == "Resposta do modelo."
    assert result["resolved"] is False
    assert result["issue_resolved"] is False
    assert result["sources"] == [doc["title"] for doc in retrieve("O que é chargeback?")]


def test_meta_answer_without_sources_is_still_delivered_unresolved():
    result = KnowledgeAgent().answer("Como faço para cadastrar meu negócio no Getnet?")
    assert result["response"] == "A base de conhecimento da Getnet não contém um artigo sobre o cadastro inicial de um negócio."
    assert result["sources"] == []
    assert result["resolved"] is False


def test_wifi_meta_answer_has_no_undocumented_recommendations():
    result = KnowledgeAgent().answer("Como configurar o Wi-Fi na sua maquininha Getnet?")
    response = result["response"].lower()
    for claim in ("3g/4g", "senha", "atendimento", "confira"):
        assert claim not in response
    assert "não há instruções suficientes" in response
    assert result["sources"] == []
    assert result["resolved"] is False


def test_error_documents_are_the_six_error_pages_of_the_corpus():
    assert sorted(error_documents()) == ["adq 1-50", "adq 4-23", "adq 4-27", "adq 4-30", "adq 4-83", "adq 4-91"]


@pytest.mark.parametrize(
    ("text", "codes"),
    [
        ("Erro ADQ 4-83 na maquininha", ["adq 4-83"]),
        ("erro adq 4 - 83", ["adq 4-83"]),
        ("Erro IDL 1-08 e S-2074", ["idl 1-08", "s-2074"]),
        ("erro ao imprimir", []),
    ],
)
def test_error_codes_are_extracted_from_the_message(text, codes):
    assert error_codes(text) == codes


def test_unknown_error_code_says_it_is_not_in_the_base():
    result = KnowledgeAgent().answer("Minha maquininha mostra erro ADQ 9-99")
    assert result["response"] == "Não encontrei informações sobre o código ADQ 9-99 na base de conhecimento da Getnet."
    assert result["sources"] == []
    assert result["resolved"] is False


def test_customer_support_hands_off_an_unknown_error_code_instead_of_citing_the_documentation():
    from app.agents.customer_support import CustomerSupportAgent

    assert CustomerSupportAgent._knowledge_followup("Minha maquininha mostra erro ADQ 9-99") is None
