#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app

SCENARIOS = [
    {
        "name": "knowledge_pix",
        "message": "Como funciona o Pix?",
        "user_id": "cliente1988",
        "expect_agent": "knowledge",
    },
    {
        "name": "knowledge_error_adq",
        "message": "Qual é o significado do erro ADQ 4-83 na maquininha?",
        "user_id": "cliente1988",
        "expect_agent": "knowledge",
    },
    {
        "name": "web_search_weather",
        "message": "Qual é a previsão do tempo em Porto Alegre amanhã?",
        "user_id": "cliente1988",
        "expect_agent": "web_search",
    },
    {
        "name": "customer_support_transaction",
        "message": "Minha transação txn1001 foi recusada e eu quero saber o status.",
        "user_id": "cliente1988",
        "expect_agent": "customer_support",
    },
    {
        "name": "human_escalation",
        "message": "Preciso falar com um humano sobre dados sensíveis do meu cadastro.",
        "user_id": "cliente1988",
        "expect_agent": "human_escalation",
    },
]


def run_validation() -> list[dict]:
    client = TestClient(app)
    results = []

    for scenario in SCENARIOS:
        response = client.post(
            "/chat",
            json={"message": scenario["message"], "user_id": scenario["user_id"]},
        )
        body = response.json()
        record = {
            "name": scenario["name"],
            "input": {
                "message": scenario["message"],
                "user_id": scenario["user_id"],
            },
            "expected_agent": scenario["expect_agent"],
            "actual_agent": body.get("agent"),
            "tool_used": body.get("tool_used"),
            "handoff_required": body.get("handoff_required"),
            "response": body.get("response"),
        }
        results.append(record)

    return results


def main() -> None:
    results = run_validation()
    output_dir = ROOT / "logs"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"validation_{timestamp}.json"
    output_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n[LOG] Resultados salvos em: {output_file}")


if __name__ == "__main__":
    main()
