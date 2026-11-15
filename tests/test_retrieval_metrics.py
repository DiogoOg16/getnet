"""EVAL-02: Recall@K e MRR sobre os documentos gold dos critérios v1.3."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import retrieval_metrics as metrics  # noqa: E402

from app.orchestrator import DECLINED_SALE_QUERY  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- cálculo das métricas ----------------------------------------------------

def test_recall_at_k_counts_relevant_documents_in_the_top_k():
    ranked = ["a", "b", "c", "d"]

    assert metrics.recall_at_k(ranked, {"a"}, 1) == 1.0
    assert metrics.recall_at_k(ranked, {"c", "z"}, 3) == 0.5
    assert metrics.recall_at_k(ranked, {"d"}, 3) == 0.0
    assert metrics.recall_at_k(ranked, {"d"}, 10) == 1.0


def test_reciprocal_rank_uses_the_first_relevant_document():
    ranked = ["a", "b", "c"]

    assert metrics.reciprocal_rank(ranked, {"a"}) == 1.0
    assert metrics.reciprocal_rank(ranked, {"c", "b"}) == 0.5
    assert metrics.reciprocal_rank(ranked, {"z"}) == 0.0


@pytest.mark.parametrize("call", [
    lambda: metrics.recall_at_k(["a"], set(), 1),
    lambda: metrics.recall_at_k(["a"], {"a"}, 0),
    lambda: metrics.reciprocal_rank(["a"], set()),
])
def test_invalid_inputs_are_rejected(call):
    with pytest.raises(ValueError):
        call()


# --- casos e consultas ---------------------------------------------------------

def test_cases_are_the_scenarios_with_required_gold_documents():
    cases = {case["id"]: case for case in metrics.load_cases()}

    assert set(cases) == {"S01", "S04", "S06", "S08", "S09", "S10"}
    assert cases["S08"]["query"] == DECLINED_SALE_QUERY
    assert cases["S04"]["query"] == "Do I need a bank account to receive my sales via Pix?"
    assert set(cases["S09"]["required"].values()) == {267, 183}


def test_ranking_matches_the_production_retrieval_limit():
    for case in metrics.load_cases():
        assert metrics.rank(case["query"])[: metrics.PRODUCTION_LIMIT] == metrics.rank(
            case["query"], limit=metrics.PRODUCTION_LIMIT
        ), case["id"]


# --- resultado sobre o corpus atual --------------------------------------------

@pytest.fixture(scope="module")
def result():
    return metrics.evaluate()


def test_metrics_agree_with_the_documented_retrieval_gaps(result):
    rows = {row["id"]: row for row in result["rows"]}

    # Requisitos de recuperação ainda em xfail nos critérios v1.3.
    assert rows["S04"]["required_positions"]["L16"] > 3   # RAG-07a
    assert rows["S06"]["required_positions"]["L145"] > 3  # RAG-07b
    assert rows["S09"]["required_positions"]["L183"] > 3  # RAG-07c
    # Documentos que os testes da camada 1 exigem e que estão no contexto.
    assert rows["S08"]["required_positions"]["L48"] <= 3  # ARCH-02 corrigido
    assert rows["S09"]["required_positions"]["L267"] <= 3
    assert rows["S01"]["required_positions"]["L269"] <= 3
    assert rows["S10"]["required_positions"]["L203"] <= 3


def test_result_is_complete_and_serializable(result):
    summary = result["summary"]

    assert summary["cases"] == len(result["rows"]) == 6
    assert set(summary["mean_recall"]) == set(metrics.K_VALUES)
    assert 0.0 <= summary["mrr"] <= 1.0
    for row in result["rows"]:
        recalls = [row["recall"][k] for k in metrics.K_VALUES]
        assert recalls == sorted(recalls), row["id"]  # Recall@K não diminui com K
    json.dumps(result)
    assert "| **Média (6)** |" in metrics.to_markdown(result)


def test_evaluation_does_not_modify_criteria_or_corpus():
    watched = [
        ROOT / "eval" / "official_scenarios.json",
        ROOT / "eval" / "official_scenarios_rubrics.md",
        ROOT / "app" / "rag" / "documents" / "getnet_sources.jsonl",
    ]
    before = {path: sha256(path) for path in watched}

    metrics.evaluate()

    assert {path: sha256(path) for path in watched} == before
