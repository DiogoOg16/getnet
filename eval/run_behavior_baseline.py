"""Run behavior dataset cases and persist a reproducible baseline report.

This script complements the pytest suite by generating a machine-readable
snapshot of per-case outcomes and aggregate metrics for before/after
comparisons.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app, handoff_store, session_memory

CASES_PATH = ROOT / "eval" / "behavior_cases_v1.json"
OUTPUT_PATH = ROOT / "eval" / "behavior_baseline_v1_results.json"

TOKEN_BY_USER = {
    "cliente1988": "test-token-cliente1988",
    "cliente2001": "test-token-cliente2001",
    "atendente_01": "test-token-atendente_01",
}

os.environ["GETNET_DEMO_AUTH_TOKENS"] = json.dumps(
    {
        "test-token-cliente1988": "cliente1988",
        "test-token-cliente2001": "cliente2001",
        "test-token-atendente_01": "atendente_01",
    }
)


def _client_for(user_id: str) -> TestClient:
    token = TOKEN_BY_USER[user_id]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _status_ok(response) -> bool:
    return response.status_code == 200


def _agent_ok(case: dict, payload: dict) -> bool:
    if "expected_agent" in case:
        return payload.get("agent") == case["expected_agent"]
    expected_agents = case.get("expected_agents", [])
    return payload.get("agent") in expected_agents


def _handoff_ok(case: dict, payload: dict) -> bool:
    expected_handoff = case.get("expected_handoff")
    if expected_handoff is None:
        return True
    return payload.get("handoff_required") is expected_handoff


def _sources_ok(case: dict, payload: dict) -> bool:
    min_sources = case.get("expected_sources_min")
    if min_sources is None:
        return True
    return len(payload.get("sources", [])) >= min_sources


def _resolved_ok(case: dict, payload: dict) -> bool:
    expected = case.get("expected_issue_resolved")
    if expected is None:
        return True
    return payload.get("issue_resolved") is expected


def _step_status_ok(case: dict, payload: dict) -> bool:
    expected = case.get("expected_step_status")
    if expected is None:
        return True
    return payload.get("step_status") == expected


def main() -> None:
    with CASES_PATH.open("r", encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]

    results: list[dict] = []

    for case in cases:
        client = _client_for(case["user_id"])
        session_id = f"baseline-{case['id'].lower()}"

        # Ensure deterministic case isolation even outside pytest fixtures.
        session_memory.clear_session(user_id=case["user_id"], session_id=session_id)
        for ticket_id, record in list(handoff_store._records.items()):
            if (
                record.get("user_id") == case["user_id"]
                and record.get("session_id") == session_id
            ):
                handoff_store._records.pop(ticket_id, None)
        handoff_store._save()

        for setup_message in case.get("setup_messages", []):
            client.post(
                "/chat",
                json={
                    "message": setup_message,
                    "user_id": case["user_id"],
                    "session_id": session_id,
                },
            )

        response = client.post(
            "/chat",
            json={
                "message": case["message"],
                "user_id": case["user_id"],
                "session_id": session_id,
            },
        )

        payload = response.json() if response.status_code == 200 else {}

        checks = {
            "http_ok": _status_ok(response),
            "agent_ok": _agent_ok(case, payload),
            "handoff_ok": _handoff_ok(case, payload),
            "sources_ok": _sources_ok(case, payload),
            "resolved_ok": _resolved_ok(case, payload),
            "step_status_ok": _step_status_ok(case, payload),
        }
        passed = all(checks.values())

        results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "session_mode": case["session_mode"],
                "checks": checks,
                "passed": passed,
                "http_status": response.status_code,
                "observed_agent": payload.get("agent"),
                "observed_handoff_required": payload.get("handoff_required"),
                "observed_step_status": payload.get("step_status"),
                "observed_issue_resolved": payload.get("issue_resolved"),
                "observed_sources_count": len(payload.get("sources", [])) if payload else 0,
                "response_excerpt": (payload.get("response", "")[:200] if payload else ""),
            }
        )

    total = len(results)
    pass_count = sum(1 for item in results if item["passed"])

    routing_cases = [
        item for item in results
        if item["checks"]["http_ok"]
    ]
    routing_ok = sum(1 for item in routing_cases if item["checks"]["agent_ok"])

    source_required_cases = [
        case for case in cases if "expected_sources_min" in case
    ]
    source_required_ids = {case["id"] for case in source_required_cases}
    source_ok = sum(
        1 for item in results
        if item["id"] in source_required_ids and item["checks"]["sources_ok"]
    )

    output = {
        "dataset": "behavior_cases_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_cases": total,
            "all_checks_passed": pass_count,
            "all_checks_pass_rate": round(pass_count / total, 4) if total else 0.0,
            "routing_correct_cases": routing_ok,
            "routing_correct_rate": round(routing_ok / len(routing_cases), 4) if routing_cases else 0.0,
            "source_evidence_cases": len(source_required_cases),
            "source_evidence_passed": source_ok,
            "source_evidence_pass_rate": (
                round(source_ok / len(source_required_cases), 4)
                if source_required_cases else 0.0
            ),
        },
        "results": results,
    }

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"Saved baseline report: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
