from fastapi.testclient import TestClient

from app.main import app

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
