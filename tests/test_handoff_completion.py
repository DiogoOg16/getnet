"""Só o atendente que assumiu o ticket pode concluí-lo.

A regra é verificada na camada de domínio (HumanHandoffStore.complete) e na
rota HTTP, que traduz a recusa em 403.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.human_handoff import HandoffPermissionError, HumanHandoffStore
from app.main import app, handoff_store

TOKENS = {
    "test-token-cliente1988": "cliente1988",
    "test-token-atendente_01": "atendente_01",
    "test-token-atendente_02": "atendente_02",
}


@pytest.fixture
def two_attendants(monkeypatch):
    monkeypatch.setenv("GETNET_DEMO_AUTH_TOKENS", json.dumps(TOKENS))


def as_user(token: str) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def assigned_ticket(session_id: str) -> str:
    response = as_user("test-token-cliente1988").post(
        "/chat",
        json={
            "message": "Preciso falar com um humano sobre dados sensíveis do meu cadastro.",
            "user_id": "cliente1988",
            "session_id": session_id,
        },
    )
    assert response.status_code == 200
    ticket_id = response.json()["handoff"]["id"]
    assumed = as_user("test-token-atendente_01").post(
        f"/human-handoff/{ticket_id}/assume", json={"assignee": "atendente_01"}
    )
    assert assumed.status_code == 200
    return ticket_id


# --- camada de domínio ------------------------------------------------------

def test_store_lets_the_assigned_attendant_complete(tmp_path):
    store = HumanHandoffStore(storage_path=str(tmp_path / "tickets.json"))
    ticket = store.create(user_id="cliente1988", session_id="s1", message="ajuda")
    store.assume(ticket["id"], "atendente_01")

    record = store.complete(ticket["id"], "Resolvido", actor="atendente_01")

    assert record["status"] == "completed"
    assert record["resolution"] == "Resolvido"


@pytest.mark.parametrize("actor", ["atendente_02", "cliente1988", ""])
def test_store_refuses_completion_by_anyone_else_and_keeps_the_ticket(tmp_path, actor):
    path = tmp_path / "tickets.json"
    store = HumanHandoffStore(storage_path=str(path))
    ticket = store.create(user_id="cliente1988", session_id="s1", message="ajuda")
    store.assume(ticket["id"], "atendente_01")

    with pytest.raises(HandoffPermissionError):
        store.complete(ticket["id"], "Resolvido", actor=actor)

    for record in (store.get(ticket["id"]), json.loads(path.read_text(encoding="utf-8"))[ticket["id"]]):
        assert record["status"] == "assigned"
        assert record["assignee"] == "atendente_01"
        assert record["resolution"] is None


def test_store_requires_an_actor():
    with pytest.raises(TypeError):
        HumanHandoffStore.complete(handoff_store, "qualquer", "Resolvido")  # sem actor


# --- rota HTTP --------------------------------------------------------------

def test_assigned_attendant_completes_over_http(two_attendants):
    ticket_id = assigned_ticket("completion-ok")

    completed = as_user("test-token-atendente_01").post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    )

    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_other_attendant_gets_403_and_ticket_stays_assigned(two_attendants):
    ticket_id = assigned_ticket("completion-other")

    denied = as_user("test-token-atendente_02").post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido por outro"}
    )

    assert denied.status_code == 403
    after = as_user("test-token-atendente_01").get(f"/human-handoff/{ticket_id}").json()
    assert after["status"] == "assigned"
    assert after["assignee"] == "atendente_01"
    assert after["resolution"] is None
    stored = json.loads(handoff_store.storage_path.read_text(encoding="utf-8"))[ticket_id]
    assert stored["status"] == "assigned"

    # O atendente atribuído continua podendo concluir depois da tentativa negada.
    completed = as_user("test-token-atendente_01").post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    )
    assert completed.status_code == 200


def test_non_attendant_still_gets_403(two_attendants):
    ticket_id = assigned_ticket("completion-customer")

    denied = as_user("test-token-cliente1988").post(
        f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}
    )

    assert denied.status_code == 403
    after = as_user("test-token-atendente_01").get(f"/human-handoff/{ticket_id}").json()
    assert after["status"] == "assigned"
