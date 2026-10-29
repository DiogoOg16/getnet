import pytest
from fastapi.testclient import TestClient

from app.main import app


clients = {
    "cliente1988": TestClient(
        app,
        headers={"Authorization": "Bearer test-token-cliente1988"},
    ),
    "cliente2001": TestClient(
        app,
        headers={"Authorization": "Bearer test-token-cliente2001"},
    ),
}


def _payload_for(message: str, *, user_id: str = "cliente1988", session_id: str | None = None):
    client = clients[user_id]
    body = {"message": message, "user_id": user_id}
    if session_id is not None:
        body["session_id"] = session_id
    return client.post("/chat", json=body).json()


def test_complete_grounded_answer_contract():
    payload = _payload_for("Qual o status da transação txn1001?")

    assert payload["response_delivered"] is True
    assert payload["flow_completed"] is True
    assert payload["issue_resolved"] is True
    assert payload["resolved"] is True
    assert payload["step_status"] == "success"
    assert payload["awaiting_user_input"] is False


def test_waiting_for_user_input_contract():
    payload = _payload_for("Minha transação foi recusada e eu quero saber o motivo.")

    assert payload["response_delivered"] is True
    assert payload["flow_completed"] is True
    assert payload["issue_resolved"] is False
    assert payload["resolved"] is False
    assert payload["awaiting_user_input"] is True
    assert payload["step_status"] == "waiting_for_user_input"


def test_generic_response_without_diagnosis_is_not_resolved():
    payload = _payload_for("Minha maquininha não conecta na internet e não funciona.")

    assert payload["response_delivered"] is True
    assert payload["flow_completed"] is True
    assert payload["issue_resolved"] is False
    assert payload["resolved"] is False
    assert payload["awaiting_user_input"] is True
    assert payload["step_status"] == "waiting_for_user_input"


def test_terminal_failure_preserves_flow_completed_true(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("tool failure")

    monkeypatch.setattr("app.main.orchestrator.support.answer", boom)

    payload = _payload_for("Para saber o motivo da transação txn1001")

    assert payload["flow_completed"] is True
    assert payload["response_delivered"] is True
    assert payload["issue_resolved"] is False
    assert payload["step_status"] == "failed"
    assert payload["awaiting_user_input"] is False


def test_human_handoff_contract():
    payload = _payload_for("Não consigo continuar e preciso falar com um humano.")

    assert payload["flow_completed"] is True
    assert payload["response_delivered"] is True
    assert payload["issue_resolved"] is False
    assert payload["handoff_required"] is True
    assert payload["step_status"] == "handoff"
    assert payload["awaiting_user_input"] is False


def test_support_then_knowledge_requires_final_resolution_evaluation():
    payload = _payload_for(
        "Por que a transação txn2001 foi recusada e como resolver?",
        user_id="cliente2001",
    )

    assert payload["flow_completed"] is True
    assert payload["response_delivered"] is True
    assert payload["issue_resolved"] is True
    assert payload["resolved"] is True
    assert payload["step_status"] == "success"
    assert payload["awaiting_user_input"] is False
