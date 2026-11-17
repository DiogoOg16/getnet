"""EVAL-02: métricas de recuperação dos cenários oficiais.

Determinístico: usa só `retrieve` (por padrão, `app.rag.retriever.retrieve`, o
de produção), sem LLM e sem rede. Os critérios (`eval/official_scenarios.json`)
e o corpus não são alterados.

Metodologia
- Casos: os cenários com documentos `required` em `layer1.gold_documents`
  (S01, S04, S06, S08, S09, S10 na v1.3+). Cenários sem documento gold
  (ferramentas externas, dados do cliente ou lacuna do corpus) ficam de fora.
  O fixture de 61 consultas não tem rótulo de relevância e nunca entra aqui.
- Consulta: o texto que o sistema de fato envia ao `retrieve` naquele cenário.
  Nos cenários do Knowledge é a mensagem do usuário; no S08 é a consulta fixa
  que o orquestrador usa depois de uma transação negada sem motivo
  (`DECLINED_SALE_QUERY`).
- Identidade do documento: sha256 (12 hex) do conteúdo, como nos critérios.
- Ranking: `retrieve(consulta, limit=MAX_RANK)`. O teste confere que os 3
  primeiros coincidem com `retrieve(consulta)` (limit=3, o de produção).
- Recall@K: fração dos documentos `required` presentes nos K primeiros.
- Precision@K: fração dos K primeiros que é `required` (divide por K).
- MRR: média de 1/posição do primeiro documento `required` nos MAX_RANK
  primeiros (0 se nenhum aparece). Com mais de um `required` (S09), considera
  só o primeiro; ler junto com o Recall@K.
- nDCG@K: ganho exponencial (2^rel − 1) / log2(posição + 1), como no BEIR.
  Principal: relevância binária sobre `required` (rel = 1).
  Secundário, "graduado": `required` = 2 e `any_of`/`supporting` = 1. É uma
  escolha deste código de avaliação, não dos critérios congelados.
- Recall@K ampliado: Recall sobre `required` + `any_of` + `supporting`.
- Latência: tempo de cada chamada ao retriever, por consulta e agregado.

Uso:
  python eval/retrieval_metrics.py            # tabela em Markdown
  python eval/retrieval_metrics.py --json OUT # também grava o resultado em JSON

Para comparar estratégias sem tocar na produção, passe outro retriever:
  evaluate(retriever=minha_funcao)  # minha_funcao(query, limit) -> [{"content": ...}, ...]
  compare(evaluate(), evaluate(retriever=minha_funcao))
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.orchestrator import DECLINED_SALE_QUERY  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402

CRITERIA_PATH = ROOT / "eval" / "official_scenarios.json"
K_VALUES = (1, 3, 5, 10)
MAX_RANK = 10
PRODUCTION_LIMIT = 3
REQUIRED_GRADE = 2
EXTENDED_GRADE = 1
# Consulta efetivamente enviada ao retrieve quando não é a mensagem do usuário.
QUERY_OVERRIDES = {"S08": (DECLINED_SALE_QUERY, "orchestrator.DECLINED_SALE_QUERY")}

Retriever = Callable[..., list[dict]]


def content_id(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


# --- métricas -------------------------------------------------------------------

def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("relevant must not be empty")
    if k < 1:
        raise ValueError("k must be >= 1")
    return len(relevant & set(ranked[:k])) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Fração dos K primeiros que é relevante; divide por K mesmo se vierem menos."""
    if k < 1:
        raise ValueError("k must be >= 1")
    return sum(1 for doc_id in ranked[:k] if doc_id in relevant) / k


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    if not relevant:
        raise ValueError("relevant must not be empty")
    for position, doc_id in enumerate(ranked, start=1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


def dcg_at_k(gains: Sequence[float], k: int) -> float:
    """DCG com ganho exponencial: soma de (2^rel − 1) / log2(posição + 1)."""
    return sum((2.0 ** gain - 1.0) / math.log2(position + 2) for position, gain in enumerate(gains[:k]))


def ndcg_at_k(ranked: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    """DCG do ranking dividido pelo DCG ideal (todos os relevantes, maior grau primeiro)."""
    if not grades:
        raise ValueError("grades must not be empty")
    ideal = dcg_at_k(sorted(grades.values(), reverse=True), k)
    return dcg_at_k([grades.get(doc_id, 0) for doc_id in ranked], k) / ideal if ideal else 0.0


# --- casos e ranking ------------------------------------------------------------

def load_cases(criteria: dict | None = None) -> list[dict]:
    criteria = criteria or json.loads(CRITERIA_PATH.read_text(encoding="utf-8"))
    cases = []
    for scenario in criteria["scenarios"]:
        gold = scenario.get("layer1", {}).get("gold_documents", {})
        required = gold.get("required", [])
        if not required:
            continue
        extra = gold.get("any_of", []) + gold.get("supporting", [])
        query, query_source = QUERY_OVERRIDES.get(scenario["id"], (scenario.get("message"), "message"))
        if not query:
            raise ValueError(f"{scenario['id']}: sem consulta definida")
        grades = {doc["content_sha256_12"]: EXTENDED_GRADE for doc in extra}
        grades.update({doc["content_sha256_12"]: REQUIRED_GRADE for doc in required})
        cases.append({
            "id": scenario["id"],
            "query": query,
            "query_source": query_source,
            "required": {doc["content_sha256_12"]: doc["line"] for doc in required},
            "extended": {doc["content_sha256_12"]: doc["line"] for doc in required + extra},
            "grades": grades,
        })
    return cases


def rank(query: str, limit: int = MAX_RANK, retriever: Retriever | None = None) -> list[str]:
    search = retriever or retrieve
    return [content_id(doc["content"]) for doc in search(query, limit=limit)]


def evaluate(cases: list[dict] | None = None, retriever: Retriever | None = None, name: str = "bm25_producao") -> dict:
    cases = cases if cases is not None else load_cases()
    if cases:
        # Aquecimento: a primeira chamada constrói o índice; não entra na latência.
        rank(cases[0]["query"], retriever=retriever)
    rows = []
    for case in cases:
        started = time.perf_counter()
        ranked = rank(case["query"], retriever=retriever)
        latency_ms = (time.perf_counter() - started) * 1000
        required, extended = set(case["required"]), set(case["extended"])
        binary = {doc_id: 1 for doc_id in required}
        graded = case.get("grades") or {doc_id: REQUIRED_GRADE for doc_id in required}
        positions = {
            line: (ranked.index(doc_id) + 1 if doc_id in ranked else None)
            for doc_id, line in case["required"].items()
        }
        rows.append({
            "id": case["id"],
            "query": case["query"],
            "query_source": case["query_source"],
            "required_positions": {f"L{line}": pos for line, pos in positions.items()},
            "recall": {k: recall_at_k(ranked, required, k) for k in K_VALUES},
            "recall_extended": {k: recall_at_k(ranked, extended, k) for k in K_VALUES},
            "precision": {k: precision_at_k(ranked, required, k) for k in K_VALUES},
            "ndcg": {k: ndcg_at_k(ranked, binary, k) for k in K_VALUES},
            "ndcg_graded": {k: ndcg_at_k(ranked, graded, k) for k in K_VALUES},
            "reciprocal_rank": reciprocal_rank(ranked, required),
            "latency_ms": round(latency_ms, 2),
            "top": ranked,
        })
    count = len(rows)

    def mean(metric: str) -> dict:
        return {k: sum(r[metric][k] for r in rows) / count for k in K_VALUES}

    latencies = [r["latency_ms"] for r in rows]
    summary = {
        "cases": count,
        "mean_recall": mean("recall"),
        "mean_recall_extended": mean("recall_extended"),
        "mean_precision": mean("precision"),
        "mean_ndcg": mean("ndcg"),
        "mean_ndcg_graded": mean("ndcg_graded"),
        "mrr": sum(r["reciprocal_rank"] for r in rows) / count,
        "latency_ms": {"mean": round(sum(latencies) / count, 2), "max": round(max(latencies), 2)},
    }
    return {"retriever": name, "k_values": list(K_VALUES), "max_rank": MAX_RANK,
            "production_limit": PRODUCTION_LIMIT, "rows": rows, "summary": summary}


def compare(baseline: dict, candidate: dict) -> list[dict]:
    """Diferença por cenário (candidato − baseline), para nenhuma média esconder regressão."""
    base_rows = {row["id"]: row for row in baseline["rows"]}
    changes = []
    for row in candidate["rows"]:
        base = base_rows[row["id"]]
        delta = {
            "R@3": row["recall"][3] - base["recall"][3],
            "nDCG@3": row["ndcg"][3] - base["ndcg"][3],
            "RR": row["reciprocal_rank"] - base["reciprocal_rank"],
        }
        changes.append({
            "id": row["id"],
            "positions": {"antes": base["required_positions"], "depois": row["required_positions"]},
            "delta": {key: round(value, 4) for key, value in delta.items()},
            "regression": any(value < 0 for value in delta.values()),
        })
    return changes


def to_markdown(result: dict) -> str:
    ks = result["k_values"]
    header = (
        "| Cenário | Posição dos `required` | " + " | ".join(f"R@{k}" for k in ks)
        + " | RR | nDCG@3 | R@3 ampliado | ms |"
    )
    lines = [header, "|" + "---|" * (len(ks) + 6)]
    absent = f">{result['max_rank']}"
    for row in result["rows"]:
        positions = ", ".join(f"{doc}: {pos or absent}" for doc, pos in row["required_positions"].items())
        recalls = " | ".join(f"{row['recall'][k]:.2f}" for k in ks)
        lines.append(
            f"| {row['id']} | {positions} | {recalls} | {row['reciprocal_rank']:.2f} | "
            f"{row['ndcg'][3]:.2f} | {row['recall_extended'][3]:.2f} | {row['latency_ms']:.1f} |"
        )
    summary = result["summary"]
    means = " | ".join(f"{summary['mean_recall'][k]:.2f}" for k in ks)
    lines.append(
        f"| **Média ({summary['cases']})** | | {means} | **MRR {summary['mrr']:.2f}** | "
        f"{summary['mean_ndcg'][3]:.2f} | {summary['mean_recall_extended'][3]:.2f} | {summary['latency_ms']['mean']:.1f} |"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="grava o resultado completo neste arquivo")
    args = parser.parse_args()
    result = evaluate()
    print(to_markdown(result))
    if args.json:
        Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
