from app.agents.customer_support import CustomerSupportAgent
from app.tools.customer_tools import (
    lookup_customer,
    lookup_settlement,
    lookup_transaction,
)


def test_lookup_existing_customer():
    result = lookup_customer("cliente1988")

    assert result["found"] is True
    assert result["customer"]["account_status"] == "active"


def test_lookup_unknown_customer():
    result = lookup_customer("cliente_inexistente")

    assert result["found"] is False


def test_lookup_transaction_owned_by_customer():
    result = lookup_transaction("txn1001", "cliente1988")

    assert result["found"] is True
    assert result["transaction"]["status"] == "approved"


def test_customer_cannot_lookup_another_customers_transaction():
    result = lookup_transaction("txn2001", "cliente1988")

    assert result["found"] is False


def test_agent_does_not_reveal_other_customers_transaction_details():
    result = CustomerSupportAgent().answer(
        "Por que a transação txn2001 foi recusada e como resolver?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["issue_resolved"] is False
    assert "não encontrei" in result["response"].lower()
    assert "R$ 250.00" not in result["response"]


def test_agent_answers_transaction_question():
    result = CustomerSupportAgent().answer(
        "Qual o status da transação txn1001?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["tool_used"] == "lookup_transaction"
    assert "aprovada" in result["response"]


def test_agent_answers_customer_account_question():
    result = CustomerSupportAgent().answer(
        "Quero consultar minha conta",
        "cliente1988",
    )

    assert result["tool_used"] == "lookup_customer"
    assert "Cliente de Teste" in result["response"]


def test_agent_handles_settlement_timing_question_without_transaction_id():
    result = CustomerSupportAgent().answer(
        "Quando o dinheiro das vendas de ontem será depositado?",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert "prazo" in result["response"].lower()
    assert "transação" in result["response"].lower() or "txn" in result["response"].lower()

def test_agent_gives_guidance_for_declined_transaction_without_id():
    result = CustomerSupportAgent().answer(
        "My card machine is showing a transaction decline error.",
        "cliente1988",
    )

    assert result["agent"] == "customer_support"
    assert result["tool_used"] is None
    assert (
        "recus" in result["response"].lower()
        or "declin" in result["response"].lower()
    )
    assert "txn" in result["response"].lower()

def test_lookup_settlement_returns_simulated_data():
    result = lookup_settlement("cliente1988")

    assert result["found"] is True
    assert result["simulated"] is True
    assert result["customer_id"] == "cliente1988"
    assert "message" in result


def test_lookup_settlement_rejects_unknown_customer():
    result = lookup_settlement("cliente_inexistente")

    assert result["found"] is False
