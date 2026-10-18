from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_chat_routes_product_question_to_knowledge():
    response = client.post(
        "/chat",
        json={
            "message": "Como funciona o Pix?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent"] == "knowledge"
    assert data["sources"]
    assert data["user_id"] == "cliente1988"


def test_chat_routes_transaction_question_to_support():
    response = client.post(
        "/chat",
        json={
            "message": "Qual o status da transação txn1001?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent"] == "customer_support"
    assert data["tool_used"] == "lookup_transaction"
    assert "aprovada" in data["response"]


def test_chat_routes_unknown_question_to_fallback():
    response = client.post(
        "/chat",
        json={
            "message": "Quero conversar sobre outro assunto",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    assert response.json()["agent"] == "fallback"


def test_chat_does_not_expose_another_customers_transaction():
    response = client.post(
        "/chat",
        json={
            "message": "Qual o status da transação txn2001?",
            "user_id": "cliente1988",
        },
    )

    assert response.status_code == 200
    assert "não encontrei" in response.json()["response"].casefold()
