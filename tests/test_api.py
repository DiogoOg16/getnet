from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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