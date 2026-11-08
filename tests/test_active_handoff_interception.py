"""Com um handoff aberto, só perguntas sobre o próprio atendimento são interceptadas.

Antes, qualquer mensagem com a palavra "status" recebia o status do handoff,
inclusive "status da transação txn1001". Os testes passam pelo /chat inteiro.
"""

import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app, handoff_store

client = TestClient(
    app,
    headers={"Authorization": "Bearer test-token-cliente1988"},
)

HANDOFF_LIFECYCLE_REASON = "The request is checking the lifecycle of an active human handoff."


def chat(message: str, session_id: str) -> dict:
    response = client.post(
        "/chat",
        json={"message": message, "user_id": "cliente1988", "session_id": session_id},
    )
    assert response.status_code == 200
    return response.json()


def open_handoff(session_id: str) -> dict:
    payload = chat("Preciso de ajuda com dados pessoais sensíveis.", session_id)
    assert payload["handoff"]["status"] == "pending"
    return payload["handoff"]


def assert_not_intercepted(payload: dict) -> None:
    assert payload["agent"] != "human_escalation"
    assert payload["routing_reason"] != HANDOFF_LIFECYCLE_REASON
    assert "atendimento humano está" not in payload["response"].lower()


def test_transaction_status_goes_to_customer_support_with_open_handoff():
    open_handoff("session-handoff-txn")

    payload = chat("Qual o status da transação txn1001?", "session-handoff-txn")

    assert_not_intercepted(payload)
    assert payload["agent"] == "customer_support"
    assert "txn1001" in payload["response"]


def test_sales_status_is_not_intercepted_with_open_handoff():
    open_handoff("session-handoff-sales")

    payload = chat("status das minhas vendas", "session-handoff-sales")

    assert_not_intercepted(payload)


def test_sales_ticket_average_is_not_intercepted_with_open_handoff():
    open_handoff("session-handoff-ticket-medio")

    payload = chat("Qual o ticket médio das minhas vendas?", "session-handoff-ticket-medio")

    assert_not_intercepted(payload)


@pytest.mark.parametrize(
    "message",
    [
        "qual o status do meu atendimento?",
        "Qual o status do meu atendimento humano?",
        "Como está o status do atendimento?",
        "Qual o status do meu chamado?",
        "Meu ticket já foi atendido?",
    ],
)
def test_questions_about_the_handoff_return_its_status(message):
    handoff = open_handoff("session-handoff-query")

    payload = chat(message, "session-handoff-query")

    assert payload["agent"] == "human_escalation"
    assert payload["routing_reason"] == HANDOFF_LIFECYCLE_REASON
    assert payload["handoff"]["id"] == handoff["id"]
    assert payload["handoff"]["status"] == "pending"
    assert "pendente" in payload["response"].lower()


def test_transaction_query_does_not_change_the_pending_ticket():
    handoff = open_handoff("session-handoff-unchanged")
    before = copy.deepcopy(handoff_store.get(handoff["id"]))

    chat("Qual o status da transação txn1001?", "session-handoff-unchanged")

    assert handoff_store.get(handoff["id"]) == before
    assert len(handoff_store.list_for_user("cliente1988")) == 1

    status_payload = chat("qual o status do meu atendimento?", "session-handoff-unchanged")
    assert status_payload["handoff"]["id"] == handoff["id"]
    assert status_payload["handoff"]["status"] == "pending"
