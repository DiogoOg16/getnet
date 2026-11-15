"""EVAL-02: métricas de recuperação (Recall@K e MRR) dos cenários oficiais.

Determinístico: usa só `app.rag.retriever.retrieve`, sem LLM e sem rede.
Os critérios (`eval/official_scenarios.json`) e o corpus não são alterados.

Metodologia
- Casos: os cenários com documentos `required` em `layer1.gold_documents`
  (S01, S04, S06, S08, S09, S10 na v1.3). Cenários sem documento gold
  (ferramentas externas, dados do cliente ou lacuna do corpus) ficam de fora.
- Consulta: o texto que o sistema de fato envia ao `retrieve` naquele cenário.
  Nos cenários do Knowledge é a mensagem do usuário; no S08 é a consulta fixa
  que o orquestrador usa depois de uma transação negada sem motivo
  (`DECLINED_SALE_QUERY`).
- Identidade do documento: sha256 (12 hex) do conteúdo, como nos critérios.
- Ranking: `retrieve(consulta, limit=MAX_RANK)`. O teste confere que os 3
  primeiros coincidem com `retrieve(consulta)` (limit=3, o de produção).
- Recall@K: fração dos documentos `required` presentes nos K primeiros.
- MRR: média de 1/posição do primeiro documento `required` nos MAX_RANK
  primeiros (0 se nenhum aparece).
- Recall@K ampliado: o mesmo cálculo sobre `required` + `any_of` + `supporting`
  (evidência alternativa ou complementar aceita pela rubrica).

Uso:
  python eval/retrieval_metrics.py            # tabela em Markdown
  python eval/retrieval_metrics.py --json OUT # também grava o resultado em JSON
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
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
# Consulta efetivamente enviada ao retrieve quando não é a mensagem do usuário.
QUERY_OVERRIDES = {"S08": (DECLINED_SALE_QUERY, "orchestrator.DECLINED_SALE_QUERY")}


def content_id(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("relevant must not be empty")
    if k < 1:
        raise ValueError("k must be >= 1")
    return len(relevant & set(ranked[:k])) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    if not relevant:
        raise ValueError("relevant must not be empty")
    for position, doc_id in enumerate(ranked, start=1):
        if doc_id in relevant:
            return 1.0 / position
    return 0.0


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
        cases.append({
            "id": scenario["id"],
            "query": query,
            "query_source": query_source,
            "required": {doc["content_sha256_12"]: doc["line"] for doc in required},
            "extended": {doc["content_sha256_12"]: doc["line"] for doc in required + extra},
        })
    return cases


def rank(query: str, limit: int = MAX_RANK) -> list[str]:
    return [content_id(doc["content"]) for doc in retrieve(query, limit=limit)]


def evaluate(cases: list[dict] | None = None) -> dict:
    cases = cases if cases is not None else load_cases()
    rows = []
    for case in cases:
        ranked = rank(case["query"])
        required, extended = set(case["required"]), set(case["extended"])
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
            "reciprocal_rank": reciprocal_rank(ranked, required),
        })
    count = len(rows)
    summary = {
        "cases": count,
        "mean_recall": {k: sum(r["recall"][k] for r in rows) / count for k in K_VALUES},
        "mean_recall_extended": {k: sum(r["recall_extended"][k] for r in rows) / count for k in K_VALUES},
        "mrr": sum(r["reciprocal_rank"] for r in rows) / count,
    }
    return {"k_values": list(K_VALUES), "max_rank": MAX_RANK, "production_limit": PRODUCTION_LIMIT,
            "rows": rows, "summary": summary}


def to_markdown(result: dict) -> str:
    ks = result["k_values"]
    header = "| Cenário | Posição dos `required` | " + " | ".join(f"R@{k}" for k in ks) + " | RR | R@3 ampliado |"
    lines = [header, "|" + "---|" * (len(ks) + 4)]
    absent = f">{result['max_rank']}"
    for row in result["rows"]:
        positions = ", ".join(f"{doc}: {pos or absent}" for doc, pos in row["required_positions"].items())
        recalls = " | ".join(f"{row['recall'][k]:.2f}" for k in ks)
        lines.append(
            f"| {row['id']} | {positions} | {recalls} | {row['reciprocal_rank']:.2f} | "
            f"{row['recall_extended'][3]:.2f} |"
        )
    summary = result["summary"]
    means = " | ".join(f"{summary['mean_recall'][k]:.2f}" for k in ks)
    lines.append(
        f"| **Média ({summary['cases']})** | | {means} | **MRR {summary['mrr']:.2f}** | "
        f"{summary['mean_recall_extended'][3]:.2f} |"
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
