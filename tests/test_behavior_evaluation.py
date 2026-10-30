import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app


BASE_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = BASE_DIR / "eval" / "behavior_cases_v1.json"

with CASES_PATH.open("r", encoding="utf-8") as fh:
    CASES = json.load(fh)["cases"]

TOKEN_BY_USER = {
    "cliente1988": "test-token-cliente1988",
    "cliente2001": "test-token-cliente2001",
    "atendente_01": "test-token-atendente_01",
}


def _client_for(user_id: str) -> TestClient:
    token = TOKEN_BY_USER[user_id]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _assert_expected_agent(case: dict, payload: dict) -> None:
    if "expected_agent" in case:
        assert payload.get("agent") == case["expected_agent"], (
            f"{case['id']}: expected agent={case['expected_agent']}, got {payload.get('agent')}"
        )
        return

    expected_agents = case.get("expected_agents", [])
    assert payload.get("agent") in expected_agents, (
        f"{case['id']}: expected one of {expected_agents}, got {payload.get('agent')}"
    )


def _assert_common_case_contract(case: dict, payload: dict) -> None:
    assert isinstance(payload.get("response"), str) and payload["response"].strip(), (
        f"{case['id']}: empty response"
    )
    assert payload.get("flow_completed") is True, f"{case['id']}: flow_completed must be true"
    assert payload.get("response_delivered") is True, (
        f"{case['id']}: response_delivered must be true"
    )

    expected_handoff = case.get("expected_handoff")
    if expected_handoff is not None:
        assert payload.get("handoff_required") is expected_handoff, (
            f"{case['id']}: expected handoff={expected_handoff}, got {payload.get('handoff_required')}"
        )

    expected_step_status = case.get("expected_step_status")
    if expected_step_status is not None:
        assert payload.get("step_status") == expected_step_status, (
            f"{case['id']}: expected step_status={expected_step_status}, got {payload.get('step_status')}"
        )

    expected_issue_resolved = case.get("expected_issue_resolved")
    if expected_issue_resolved is not None:
        assert payload.get("issue_resolved") is expected_issue_resolved, (
            f"{case['id']}: expected issue_resolved={expected_issue_resolved}, got {payload.get('issue_resolved')}"
        )

    expected_sources_min = case.get("expected_sources_min")
    if expected_sources_min is not None:
        assert len(payload.get("sources", [])) >= expected_sources_min, (
            f"{case['id']}: expected at least {expected_sources_min} source(s), got {len(payload.get('sources', []))}"
        )

    expected_trace_min = case.get("expected_trace_min")
    if expected_trace_min is not None:
        assert len(payload.get("trace", [])) >= expected_trace_min, (
            f"{case['id']}: expected at least {expected_trace_min} trace step(s), got {len(payload.get('trace', []))}"
        )

    for token in case.get("expected_response_contains", []):
        assert token.lower() in payload["response"].lower(), (
            f"{case['id']}: expected token '{token}' in response"
        )


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_behavior_cases(case):
    client = _client_for(case["user_id"])

    if case["session_mode"] == "isolated":
        session_id = f"behavior-{case['id'].lower()}"
    else:
        session_id = f"behavior-context-{case['id'].lower()}"

    for setup_message in case.get("setup_messages", []):
        setup_response = client.post(
            "/chat",
            json={
                "message": setup_message,
                "user_id": case["user_id"],
                "session_id": session_id,
            },
        )
        assert setup_response.status_code == 200, (
            f"{case['id']}: setup message failed"
        )

    response = client.post(
        "/chat",
        json={
            "message": case["message"],
            "user_id": case["user_id"],
            "session_id": session_id,
        },
    )

    assert response.status_code == 200, (
        f"{case['id']}: expected HTTP 200, got {response.status_code}"
    )

    payload = response.json()
    _assert_expected_agent(case, payload)
    _assert_common_case_contract(case, payload)


def test_behavior_security_cross_user_isolation():
    client = _client_for("cliente1988")

    response = client.post(
        "/chat",
        json={
            "message": "Qual o status da transação txn2001?",
            "user_id": "cliente2001",
            "session_id": "behavior-security-cross-user",
        },
    )

    assert response.status_code == 403
    assert "não corresponde" in response.json().get("detail", "").lower()


def test_behavior_session_isolation_between_parallel_sessions():
    client = _client_for("cliente1988")

    client.post(
        "/chat",
        json={
            "message": "Meu nome é Ana.",
            "user_id": "cliente1988",
            "session_id": "behavior-session-a",
        },
    )

    client.post(
        "/chat",
        json={
            "message": "Meu nome é Bruno.",
            "user_id": "cliente1988",
            "session_id": "behavior-session-b",
        },
    )

    response_a = client.post(
        "/chat",
        json={
            "message": "Qual foi o nome que eu disse?",
            "user_id": "cliente1988",
            "session_id": "behavior-session-a",
        },
    )

    response_b = client.post(
        "/chat",
        json={
            "message": "Qual foi o nome que eu disse?",
            "user_id": "cliente1988",
            "session_id": "behavior-session-b",
        },
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    assert "ana" in response_a.json().get("response", "").lower()
    assert "bruno" not in response_a.json().get("response", "").lower()

    assert "bruno" in response_b.json().get("response", "").lower()
    assert "ana" not in response_b.json().get("response", "").lower()
