"""Regressões do retriever para consultas em inglês com "bank".

Fixam o comportamento de `848ca9f`. Uma expansão de "bank" para "vincular"
foi medida e descartada: trazia "1. Vinculação da conta", que descreve o
fluxo do pagador, para o top 3 de quase toda consulta com "bank", e tirava
documentos de domicílio e de Get Conta.

Estes testes protegem o comportamento de recuperação da linha de base 848ca9f;
não garantem a qualidade semântica das respostas geradas.

O fixture de 848ca9f não é editado. As consultas cujo top 3 mudou depois dele
ficam listadas em `CHANGED_SINCE_848CA9F`, com o motivo, para que toda mudança
de ranking seja explícita e revisável.
"""

import json
from pathlib import Path

import pytest

from app.agents.router import RouterAgent
from app.rag.retriever import SYNONYMS, query_terms, retrieve

BASELINE = json.loads(
    (Path(__file__).parent / "fixtures" / "ranking_61_consultas_848ca9f.json")
    .read_text(encoding="utf-8")
)["consultas"]

LINKING = "1. Vinculação da conta (primeiro uso)"
# H1b (2026-11-17): o radical da marca ("Getnet") saiu da pontuação BM25 e da
# cobertura e ficou só no boost de título (ver retriever.BRAND_TERMS). Só as 5
# consultas do fixture com a marca e outros termos mudam; todas foram rotuladas
# no H2 (~/getnet-experiments/2026-11-16_h2-relevancia-fixture/).
CHANGED_SINCE_848CA9F = {
    "How does receivables advance (antecipação) work with Getnet?": [
        "O que é antecipação de vendas?",
        "Qual a taxa para Antecipação Automática?",
        "Como antecipar suas vendas pelo app - Getnet",
    ],
    "Como funciona a antecipação de recebíveis na Getnet?": [
        "O que é antecipação de vendas?",
        "Qual a taxa para Antecipação Automática?",
        "Como antecipar suas vendas pelo app - Getnet",
    ],
    # L116 continua em 1º; as posições 2 e 3 passam a ser documentos
    # irrelevantes (Pix Agendado, Pix Saque/Troco) no lugar de L5 e L1
    # (supporting). nDCG graduado@3: 1,00 → 0,73. Limitação conhecida.
    "Como funciona o Pix na Getnet?": [
        "Como funciona o Pix na Getnet?",
        "O que é Pix agendado? Como faço o agendamento do Pix?",
        "O que é Pix Saque e Pix Troco?",
    ],
    "Como funciona o Pix da Getnet?": [
        "Como funciona o Pix na Getnet?",
        "O que é Pix agendado? Como faço o agendamento do Pix?",
        "O que é Pix Saque e Pix Troco?",
    ],
    "Quais produtos a Getnet oferece para pequenos negócios?": [
        "Crediário: vantagens",
        "Benefícios de habilitar o Pix:",
        "Link de Pagamento: benefícios",
    ],
}

DOMICILE_CHANGE = "Como eu altero/atualizado meu domicílio bancário?"
LOCK_DIFFERENCE = "Qual é a diferença entre Gravame e Trava de Domicílio Bancário?"
GRAVAME = "O que é gravame e como ele funciona?"
OPEN_GET_CONTA = "Como faço para abrir uma Get Conta? Preciso ter uma máquina de cartão?"


def titles(query: str) -> list[str]:
    return [doc["title"] for doc in retrieve(query)]


def test_bank_maps_only_to_banco():
    assert SYNONYMS["bank"] == "banco"
    assert query_terms("bank") == ["banco"]


def test_baseline_has_the_expected_query_split():
    assert len(BASELINE) == 61
    assert sum(item["pt"] for item in BASELINE) == 49


@pytest.mark.parametrize(
    "item",
    BASELINE,
    ids=lambda item: item["consulta"][:40],
)
def test_ranking_matches_the_baseline(item):
    expected = CHANGED_SINCE_848CA9F.get(item["consulta"], item["top3"])
    assert titles(item["consulta"]) == expected


def test_changes_since_the_baseline_are_real_and_only_in_brand_queries():
    by_query = {item["consulta"]: item for item in BASELINE}
    for query, top3 in CHANGED_SINCE_848CA9F.items():
        assert query in by_query, query
        assert top3 != by_query[query]["top3"], query
        assert "getne" in query_terms(query), query


@pytest.mark.parametrize(
    "query",
    [
        "How do I change my bank domicile?",
        "How do I register my bank account?",
        "How do I link my bank account?",
        "How do I update my bank details?",
        "Do I need a bank account to use the Payment Link?",
        "Do I need a bank account for the card machine?",
        "How do I get a bank loan?",
        "Do I need a bank account to receive my sales via Pix?",
    ],
)
def test_bank_queries_do_not_pull_the_payer_linking_document(query):
    assert LINKING not in titles(query)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Qual o domicílio bancário?", DOMICILE_CHANGE),
        ("Como trocar o domicílio bancário?", DOMICILE_CHANGE),
        ("O que é trava de domicílio bancário?", LOCK_DIFFERENCE),
        ("How do I change my bank domicile?", LOCK_DIFFERENCE),
        ("How do I change my bank domicile?", GRAVAME),
        ("How do I update my bank details?", GRAVAME),
        ("Do I need a bank account for the card machine?", OPEN_GET_CONTA),
    ],
)
def test_bank_queries_keep_relevant_documents(query, expected):
    assert expected in titles(query)


@pytest.mark.parametrize(
    ("query", "agent"),
    [
        ("Is the bank open on Saturday?", "fallback"),
        ("What is a bank holiday?", "web_search"),
        ("What is the Bank of England rate?", "web_search"),
        ("Who is the best bank in Brazil?", "fallback"),
        ("bank robbery movies", "fallback"),
    ],
)
def test_off_topic_bank_queries_do_not_reach_knowledge(query, agent):
    assert RouterAgent().route(query).agent == agent
