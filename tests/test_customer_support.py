from app.agents.customer_support import CustomerSupportAgent
from app.tools.customer_tools import (
    lookup_customer,
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
