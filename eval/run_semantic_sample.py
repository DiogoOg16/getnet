"""Generate a reproducible evidence sample for assisted semantic review.

This script does not score responses. It only captures runtime outputs for a
representative subset so a human reviewer can apply the rubric independently.
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
OUTPUT_PATH = ROOT / "eval" / "semantic_sample_v1_results.json"

SAMPLE_IDS = [
    "BEH-001",
    "BEH-002",
    "BEH-004",
    "BEH-005",
    "BEH-008",
    "BEH-009",
    "BEH-014",
    "BEH-017",
    "BEH-019",
    "BEH-023",
]

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


def main() -> None:
    with CASES_PATH.open("r", encoding="utf-8") as fh:
        all_cases = json.load(fh)["cases"]

    case_by_id = {case["id"]: case for case in all_cases}
    selected_cases = [case_by_id[case_id] for case_id in SAMPLE_IDS]

    rows: list[dict] = []

    for case in selected_cases:
        client = _client_for(case["user_id"])
        session_id = f"semantic-sample-{case['id'].lower()}"

        # Explicit isolation because this script runs outside pytest fixtures.
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

        rows.append(
            {
                "id": case["id"],
                "category": case["category"],
                "session_mode": case["session_mode"],
                "question": case["message"],
                "http_status": response.status_code,
                "agent": payload.get("agent"),
                "step_status": payload.get("step_status"),
                "handoff_required": payload.get("handoff_required"),
                "issue_resolved": payload.get("issue_resolved"),
                "tool_used": payload.get("tool_used"),
                "sources": payload.get("sources", []),
                "source_sections": payload.get("source_sections", {}),
                "response": payload.get("response", ""),
            }
        )

    output = {
        "sample": "priority1_semantic_sample_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "case_ids": SAMPLE_IDS,
        "results": rows,
    }

    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Saved semantic sample evidence: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
