"""EVAL-02: Recall@K e MRR sobre os documentos gold dos critérios v1.3."""

import hashlib
import math
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


# --- R1: precision, nDCG, latência, retriever plugável, comparação -------------

RANKED = ["d1", "d2", "d3", "d4", "d5"]


def test_precision_divides_by_k():
    assert metrics.precision_at_k(RANKED, {"d2", "d4", "d9"}, 5) == pytest.approx(2 / 5)
    assert metrics.precision_at_k(["d2"], {"d2"}, 10) == pytest.approx(1 / 10)


def test_ndcg_binary_hand_computed():
    # relevantes nas posições 2 e 4; ideal = 3 relevantes nas posições 1..3
    dcg = 1 / math.log2(3) + 1 / math.log2(5)
    idcg = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
    assert metrics.ndcg_at_k(RANKED, {"d2": 1, "d4": 1, "d9": 1}, 5) == pytest.approx(dcg / idcg)


def test_ndcg_graded_prefers_the_higher_grade_first():
    assert metrics.ndcg_at_k(["a", "b"], {"a": 2, "b": 1}, 10) == pytest.approx(1.0)
    assert metrics.ndcg_at_k(["b", "a"], {"a": 2, "b": 1}, 10) < 1.0
    # ganho exponencial: grau 2 vale 3, grau 1 vale 1
    assert metrics.dcg_at_k([2, 1], 2) == pytest.approx(3 / 1 + 1 / math.log2(3))


def test_ndcg_requires_grades():
    with pytest.raises(ValueError):
        metrics.ndcg_at_k(["a"], {}, 3)


def test_result_reports_new_metrics_and_latency(result):
    summary = result["summary"]
    assert set(summary["mean_precision"]) == set(summary["mean_ndcg"]) == set(metrics.K_VALUES)
    assert summary["latency_ms"]["max"] >= summary["latency_ms"]["mean"] >= 0
    for row in result["rows"]:
        assert 0.0 <= row["ndcg"][3] <= 1.0 and 0.0 <= row["ndcg_graded"][3] <= 1.0
        assert row["latency_ms"] >= 0
    # nDCG binário bate com o Recall nos casos com um único required no top 1
    s08 = next(row for row in result["rows"] if row["id"] == "S08")
    assert s08["ndcg"][3] == 1.0


def test_pluggable_retriever_and_compare_flags_regressions():
    cases = [case for case in metrics.load_cases() if case["id"] in ("S08", "S10")]
    baseline = metrics.evaluate(cases)
    s08_gold = next(iter(cases[0]["required"]))

    def worse_retriever(query, limit=10):
        docs = metrics.retrieve(query, limit=limit)
        # Põe um documento irrelevante na frente do gold do S08, simulando uma
        # regressão (a consulta do S08 recupera só L48).
        if any(metrics.content_id(doc["content"]) == s08_gold for doc in docs):
            return [{"content": "documento irrelevante"}] + docs
        return docs

    candidate = metrics.evaluate(cases, retriever=worse_retriever, name="pior")
    changes = {change["id"]: change for change in metrics.compare(baseline, candidate)}

    assert candidate["retriever"] == "pior"
    assert changes["S08"]["regression"] is True and changes["S08"]["delta"]["RR"] < 0
    assert changes["S10"]["regression"] is False
