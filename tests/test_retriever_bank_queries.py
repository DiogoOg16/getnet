"""Regressões do retriever para consultas em inglês com "bank".

Fixam o comportamento de `848ca9f`. Uma expansão de "bank" para "vincular"
foi medida e descartada: trazia "1. Vinculação da conta", que descreve o
fluxo do pagador, para o top 3 de quase toda consulta com "bank", e tirava
documentos de domicílio e de Get Conta.

Estes testes protegem o comportamento de recuperação da linha de base 848ca9f;
não garantem a qualidade semântica das respostas geradas.
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
    assert titles(item["consulta"]) == item["top3"]


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
