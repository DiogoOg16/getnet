import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


BASE_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = BASE_DIR / "eval" / "stage5_cases.json"


with CASES_PATH.open("r", encoding="utf-8") as fh:
    cases = json.load(fh)["cases"]

BASE_CASES = [case for case in cases if case["id"] != "EVAL-008"]

client = TestClient(
    app,
    headers={"Authorization": "Bearer test-token-cliente1988"},
)


@pytest.mark.parametrize("case", BASE_CASES, ids=[case["id"] for case in BASE_CASES])
def test_stage5_routing_and_resolution_evaluation(case):
    response = client.post(
        "/chat",
        json={
            "message": case["question"],
            "user_id": "cliente1988",
            "session_id": f"eval-{case['id'].lower()}",
        },
    )

    assert response.status_code == 200, f"Case {case['id']} failed with {response.status_code}"

    payload = response.json()
    agent = payload.get("agent")
    handoff_required = payload.get("handoff_required", False)
    resolved = payload.get("resolved", False)
    response_text = payload.get("response", "")

    assert agent == case["expected_agent"], (
        f"{case['id']}: expected agent {case['expected_agent']}, got {agent}"
    )
    assert handoff_required is case["expected_handoff"], (
        f"{case['id']}: expected handoff={case['expected_handoff']}, got {handoff_required}"
    )
    assert resolved is case["expected_resolved"], (
        f"{case['id']}: expected resolved={case['expected_resolved']}, got {resolved}"
    )
    assert isinstance(response_text, str) and response_text.strip(), (
        f"{case['id']}: response text should not be empty"
    )

    for token in case.get("expected_response_contains", []):
        normalized = response_text.lower()
        assert token.lower() in normalized, (
            f"{case['id']}: expected response to mention '{token}' but got '{response_text}'"
        )

    if case["expected_handoff"]:
        ticket_id = payload["handoff"]["id"]
        ticket_response = client.get(f"/human-handoff/{ticket_id}")
        assert ticket_response.status_code == 200, (
            f"{case['id']}: ticket {ticket_id} was not persisted"
        )
        record = ticket_response.json()
        assert record["user_id"] == "cliente1988", (
            f"{case['id']}: ticket user mismatch: {record.get('user_id')}"
        )
        assert record["session_id"] == f"eval-{case['id'].lower()}", (
            f"{case['id']}: ticket session mismatch: {record.get('session_id')}"
        )

    if case["should_resolve"]:
        assert agent != "human_escalation", f"{case['id']}: expected resolution instead of human handoff"
        assert agent != "fallback", f"{case['id']}: expected a resolvable response, got fallback"


def test_stage5_eval_008_success_quote_path(monkeypatch):
    def fake_exchange_answer(message):
        return {
            "agent": "web_search",
            "response": (
                "Cotação do dólar americano (PTAX de fechamento do Banco Central, "
                "28/10/2026 13:00): compra R$ 5,0000, venda R$ 5,0500."
            ),
            "sources": ["https://www.bcb.gov.br/conversao"],
            "tool_used": "bcb_ptax",
            "issue_resolved": True,
            "resolved": True,
            "handoff_required": False,
            "awaiting_user_input": False,
            "step_status": "success",
            "flow_completed": True,
            "response_delivered": True,
        }

    monkeypatch.setattr("app.main.orchestrator.web_search.answer", fake_exchange_answer)

    response = client.post(
        "/chat",
        json={
            "message": "Qual a cotação do dólar hoje?",
            "user_id": "cliente1988",
            "session_id": "eval-eval-008-success",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    text = payload["response"].lower()

    assert payload["agent"] == "web_search"
    assert payload["handoff_required"] is False
    assert payload["issue_resolved"] is True
    assert payload["resolved"] is True
    assert "cota" in text
    assert "banco central" in text
    assert "compra" in text
    assert "venda" in text


def test_stage5_eval_008_unavailable_path(monkeypatch):
    def fake_exchange_answer(message):
        return {
            "agent": "web_search",
            "response": (
                "O serviço do Banco Central está indisponível no momento. "
                "Consulte a cotação oficial em https://www.bcb.gov.br/conversao."
            ),
            "sources": [],
            "tool_used": "bcb_ptax",
            "issue_resolved": False,
            "resolved": False,
            "handoff_required": False,
            "awaiting_user_input": False,
            "step_status": "failed",
            "flow_completed": True,
            "response_delivered": True,
        }

    monkeypatch.setattr("app.main.orchestrator.web_search.answer", fake_exchange_answer)

    response = client.post(
        "/chat",
        json={
            "message": "Qual a cotação do dólar hoje?",
            "user_id": "cliente1988",
            "session_id": "eval-eval-008-unavailable",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    text = payload["response"].lower()

    assert payload["agent"] == "web_search"
    assert payload["handoff_required"] is False
    assert payload["issue_resolved"] is False
    assert payload["resolved"] is False
    assert "indispon" in text
    assert "banco central" in text
    assert "https://www.bcb.gov.br/conversao" in text
