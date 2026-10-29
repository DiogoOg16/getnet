import pytest
from fastapi.testclient import TestClient

from app.human_handoff import HumanHandoffStore
from app.main import app
from app.session_memory import SessionMemory

client = TestClient(
    app,
    headers={"Authorization": "Bearer test-token-cliente1988"},
)

def test_chat_rejects_missing_authentication():
    unauthenticated_client = TestClient(app)

    response = unauthenticated_client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 401


def test_chat_rejects_invalid_token():
    response = client.post(
        "/chat",
        headers={"Authorization": "Bearer token-invalido"},
        json={
            "message": "Preciso de ajuda",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 401


def test_chat_rejects_mismatched_authenticated_user():
    response = client.post(
        "/chat",
        json={
            "message": "Qual o status da minha conta?",
            "user_id": "cliente2001",
        },
    )

    assert response.status_code == 403

def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat():
    response = client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == "cliente1988"
    assert response.json()["message"] == "Preciso de ajuda"


def test_chat_rejects_missing_user_id():
    response = client.post(
        "/chat",
        json={"message": "Preciso de ajuda"},
    )

    assert response.status_code == 422


def test_chat_rejects_invalid_demo_auth_configuration(monkeypatch):
    monkeypatch.setenv("GETNET_DEMO_AUTH_TOKENS", '{invalid-json')

    response = client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Configuração de autenticação indisponível."


def test_chat_escalates_when_request_is_out_of_scope():
    response = client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda com dados pessoais sensíveis e não posso prosseguir sem atendimento humano.",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "human_escalation"
    assert response.json()["handoff_required"] is True
    assert "atendimento humano" in response.json()["response"].lower()


def test_chat_groups_sources_by_section():
    response = client.post(
        "/chat",
        json={
            "message": "Como funciona o Pix da Getnet?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "source_sections" in payload
    assert isinstance(payload["source_sections"], dict)
    assert payload["source_sections"]
    assert any("pix" in key.lower() for key in payload["source_sections"])


def test_chat_groups_plugin_sources_with_plugin_section():
    response = client.post(
        "/chat",
        json={
            "message": "Quais plugins a Getnet trabalha?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert any("plugin" in key.lower() for key in payload.get("source_sections", {}))


def test_chat_does_not_log_message_content(caplog):
    import logging

    secret_marker = "PRIVACY_TEST_MARKER_938271"
    caplog.set_level(logging.INFO)

    response = client.post(
        "/chat",
        json={
            "message": f"Preciso de ajuda {secret_marker}",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    assert secret_marker not in caplog.text


def test_chat_keeps_conversation_context_for_same_session():
    response = client.post(
        "/chat",
        json={
            "message": "Meu nome é Ana e quero consultar minha conta.",
            "user_id": "cliente1988",
            "session_id": "session-ana",
        },
    )

    assert response.status_code == 200

    follow_up = client.post(
        "/chat",
        json={
            "message": "Qual foi o nome que eu acabei de dizer?",
            "user_id": "cliente1988",
            "session_id": "session-ana",
        },
    )

    assert follow_up.status_code == 200
    assert "ana" in follow_up.json()["response"].lower()


def test_chat_does_not_mix_messages_between_sessions_for_same_user():
    first = client.post(
        "/chat",
        json={
            "message": "Meu nome é Ana e quero saber sobre Pix.",
            "user_id": "cliente1988",
            "session_id": "session-ana",
        },
    )
    second = client.post(
        "/chat",
        json={
            "message": "Meu nome é Bruno e quero saber sobre Pix.",
            "user_id": "cliente1988",
            "session_id": "session-bruno",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    follow_up = client.post(
        "/chat",
        json={
            "message": "Qual é o nome que eu usei na conversa atual?",
            "user_id": "cliente1988",
            "session_id": "session-bruno",
        },
    )

    assert follow_up.status_code == 200
    assert "bruno" in follow_up.json()["response"].lower()
    assert "ana" not in follow_up.json()["response"].lower()


def test_session_memory_persists_and_recovers(tmp_path):
    storage_path = tmp_path / "session_memory.json"
    memory = SessionMemory(storage_path=str(storage_path), max_entries=10)
    memory.add_message(
        user_id="cliente1988",
        session_id="session-restart",
        message="Meu nome é Carlos.",
        response="Registro salvo.",
    )

    reloaded = SessionMemory(storage_path=str(storage_path), max_entries=10)
    context = reloaded.get_recent_context(
        user_id="cliente1988",
        session_id="session-restart",
        limit=5,
    )

    assert any("carlos" in item.lower() for item in context)


def test_human_handoff_requires_authentication_on_management_endpoints():
    unauthenticated_client = TestClient(app)

    assert unauthenticated_client.get("/human-handoff").status_code == 401
    assert unauthenticated_client.get("/human-handoff/abc123").status_code == 401
    assert unauthenticated_client.post("/human-handoff/abc123/assume", json={"assignee": "atendente_01"}).status_code == 401
    assert unauthenticated_client.post("/human-handoff/abc123/complete", json={"resolution": "Resolvido"}).status_code == 401


def test_human_handoff_rejects_customer_access_to_other_users_ticket():
    customer_client = TestClient(
        app,
        headers={"Authorization": "Bearer test-token-cliente1988"},
    )
    other_client = TestClient(
        app,
        headers={"Authorization": "Bearer test-token-cliente2001"},
    )

    first = customer_client.post(
        "/chat",
        json={
            "message": "Preciso de atendimento humano e tenho um caso sensível.",
            "user_id": "cliente1988",
            "session_id": "session-privacy",
        },
    )
    ticket_id = first.json()["handoff"]["id"]

    assert other_client.get(f"/human-handoff/{ticket_id}").status_code == 403
    assert other_client.post(f"/human-handoff/{ticket_id}/assume", json={"assignee": "atendente_02"}).status_code == 403
    assert other_client.post(f"/human-handoff/{ticket_id}/complete", json={"resolution": "Resolvido"}).status_code == 403


def test_human_handoff_rejects_invalid_transitions():
    customer_client = TestClient(
        app,
        headers={"Authorization": "Bearer test-token-cliente1988"},
    )
    support_client = TestClient(
        app,
        headers={"Authorization": "Bearer test-token-atendente_01"},
    )

    response = customer_client.post(
        "/chat",
        json={
            "message": "Preciso de atendimento humano para um caso urgente.",
            "user_id": "cliente1988",
            "session_id": "session-invalid-state",
        },
    )
    ticket_id = response.json()["handoff"]["id"]

    completed_too_early = support_client.post(
        f"/human-handoff/{ticket_id}/complete",
        json={"resolution": "Tentativa inválida"},
    )
    assert completed_too_early.status_code == 400

    assigned = support_client.post(
        f"/human-handoff/{ticket_id}/assume",
        json={"assignee": "atendente_01"},
    )
    assert assigned.status_code == 200

    repeated_assignment = support_client.post(
        f"/human-handoff/{ticket_id}/assume",
        json={"assignee": "atendente_01"},
    )
    assert repeated_assignment.status_code == 400


def test_human_handoff_creates_persistent_ticket_for_sensitive_request():
    response = client.post(
        "/chat",
        json={
            "message": "Preciso de atendimento humano para dados pessoais sensíveis.",
            "user_id": "cliente1988",
            "session_id": "session-hitl-1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] == "human_escalation"
    assert payload["handoff_required"] is True
    assert "handoff" in payload
    assert payload["handoff"]["status"] == "pending"
    assert payload["handoff"]["user_id"] == "cliente1988"
    assert payload["handoff"]["session_id"] == "session-hitl-1"

    ticket_id = payload["handoff"]["id"]
    detail = client.get(f"/human-handoff/{ticket_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "pending"


def test_human_handoff_lifecycle_can_be_assumed_and_completed():
    customer_client = TestClient(
        app,
        headers={"Authorization": "Bearer test-token-cliente2001"},
    )
    support_client = TestClient(
        app,
        headers={"Authorization": "Bearer test-token-atendente_01"},
    )

    first = customer_client.post(
        "/chat",
        json={
            "message": "Não consigo continuar e preciso falar com um humano.",
            "user_id": "cliente2001",
            "session_id": "session-hitl-2",
        },
    )
    ticket_id = first.json()["handoff"]["id"]

    assigned = support_client.post(
        f"/human-handoff/{ticket_id}/assume",
        json={"assignee": "atendente_01"},
    )
    assert assigned.status_code == 200
    assert assigned.json()["status"] == "assigned"
    assert assigned.json()["assignee"] == "atendente_01"

    completed = support_client.post(
        f"/human-handoff/{ticket_id}/complete",
        json={"resolution": "Caso resolvido pelo atendimento humano."},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert "resolvido" in completed.json()["resolution"].lower()


def test_human_handoff_keeps_user_and_session_isolated():
    client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda com dados pessoais sensíveis.",
            "user_id": "cliente1988",
            "session_id": "session-a",
        },
    )

    client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda com dados pessoais sensíveis.",
            "user_id": "cliente1988",
            "session_id": "session-b",
        },
    )

    list_response = client.get("/human-handoff")
    assert list_response.status_code == 200
    records = list_response.json()
    assert len(records) == 2
    assert {record["session_id"] for record in records} == {"session-a", "session-b"}
    assert all(record["user_id"] == "cliente1988" for record in records)

    follow_up = client.post(
        "/chat",
        json={
            "message": "Qual o status do meu atendimento humano?",
            "user_id": "cliente1988",
            "session_id": "session-a",
        },
    )
    assert follow_up.status_code == 200
    assert "pendente" in follow_up.json()["response"].lower() or "assumido" in follow_up.json()["response"].lower()


def test_active_handoff_status_response_has_explicit_contract_fields():
    first = client.post(
        "/chat",
        json={
            "message": "Preciso de ajuda com dados pessoais sensíveis.",
            "user_id": "cliente1988",
            "session_id": "session-active-contract",
        },
    )
    assert first.status_code == 200
    assert first.json()["handoff"]["status"] == "pending"

    status_response = client.post(
        "/chat",
        json={
            "message": "Qual o status do meu atendimento humano?",
            "user_id": "cliente1988",
            "session_id": "session-active-contract",
        },
    )

    assert status_response.status_code == 200
    payload = status_response.json()
    assert payload["agent"] == "human_escalation"
    assert payload["handoff_required"] is True
    assert payload["flow_completed"] is True
    assert payload["response_delivered"] is True
    assert payload["issue_resolved"] is False
    assert payload["resolved"] is False
    assert payload["awaiting_user_input"] is False
    assert payload["step_status"] == "handoff"
    assert payload["handoff"]["status"] == "pending"


def test_memory_direct_answer_marks_resolution_when_sufficient():
    response = client.post(
        "/chat",
        json={
            "message": "Meu nome é Ana e quero consultar minha conta.",
            "user_id": "cliente1988",
            "session_id": "session-memory-sufficient",
        },
    )
    assert response.status_code == 200

    follow_up = client.post(
        "/chat",
        json={
            "message": "Qual foi o nome que eu acabei de dizer?",
            "user_id": "cliente1988",
            "session_id": "session-memory-sufficient",
        },
    )

    assert follow_up.status_code == 200
    payload = follow_up.json()
    assert payload["agent"] == "memory"
    assert payload["tool_used"] == "session_memory"
    assert payload["issue_resolved"] is True
    assert payload["resolved"] is True


def test_memory_unresolved_question_falls_back_without_resolution():
    response = client.post(
        "/chat",
        json={
            "message": "Qual foi o nome que eu acabei de dizer?",
            "user_id": "cliente1988",
            "session_id": "session-memory-unresolved",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent"] != "memory"
    assert payload["issue_resolved"] is False
    assert payload["resolved"] is False


def test_human_handoff_store_raises_on_invalid_payload():
    store = HumanHandoffStore()
    with pytest.raises(ValueError):
        store.create(
            user_id="cliente1988",
            session_id="",
            message="dados sensíveis",
        )
