import json
import os
from datetime import timedelta

import pytest

from app.agents.customer_support import CustomerSupportAgent
from app.llm.ollama_client import OllamaClient
from app.tools.customer_tools import register_customer_tools, settlement_reference_date
from app.tools.registry import tool_registry

register_customer_tools(tool_registry)


@pytest.mark.network
def _requires_real_ollama_integration():
    if os.getenv("RUN_OLLAMA_INTEGRATION") != "1":
        pytest.skip(
            "Set RUN_OLLAMA_INTEGRATION=1 to execute the real customer-support integration test."
        )


class RecordingOllamaClient(OllamaClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.chat_calls: list[dict] = []

    def chat(self, messages, tools=None):
        self.chat_calls.append({
            "messages": [dict(message) for message in messages],
            "tools": tools,
        })
        return super().chat(messages, tools=tools)


def _assert_history_contains_tool_round(client, expected_tool_name, *, expected_result_keywords=()):
    assert len(client.chat_calls) >= 2
    second_call = client.chat_calls[1]
    second_messages = second_call["messages"]

    assert any(
        message.get("role") == "assistant" and "tool_calls" in message
        for message in second_messages
    )
    assert any(
        message.get("role") == "tool"
        and message.get("tool_name") == expected_tool_name
        for message in second_messages
    )

    tool_message = next(
        message
        for message in second_messages
        if message.get("role") == "tool" and message.get("tool_name") == expected_tool_name
    )
    payload = json.loads(tool_message["content"])
    assert payload["ok"] is True
    if expected_result_keywords:
        assert any(keyword in str(payload["result"]).lower() for keyword in expected_result_keywords)


@pytest.mark.network
def test_customer_support_real_integration_customer_lookup():
    _requires_real_ollama_integration()

    client = RecordingOllamaClient()
    agent = CustomerSupportAgent(client=client)

    result = agent.answer("Quero consultar meu cadastro.", "cliente1988")

    assert result["agent"] == "customer_support"
    assert result["flow_completed"] is True
    assert result["response_delivered"] is True
    assert result["tool_used"] == "lookup_customer"
    assert result["issue_resolved"] is True
    assert result["function_call_status"] == "tool_call_success"

    _assert_history_contains_tool_round(
        client,
        "lookup_customer",
        expected_result_keywords=("cliente", "active", "cliente de teste"),
    )

    assert result["response"]
    assert "Cliente" in result["response"] or "cadastro" in result["response"].lower()


@pytest.mark.network
def test_customer_support_real_integration_transaction_lookup():
    _requires_real_ollama_integration()

    client = RecordingOllamaClient()
    agent = CustomerSupportAgent(client=client)

    result = agent.answer("Qual o status da transação txn1001?", "cliente1988")

    assert result["agent"] == "customer_support"
    assert result["flow_completed"] is True
    assert result["response_delivered"] is True
    assert result["tool_used"] == "lookup_transaction"
    assert result["issue_resolved"] is True
    assert result["function_call_status"] == "tool_call_success"

    _assert_history_contains_tool_round(
        client,
        "lookup_transaction",
        expected_result_keywords=("txn1001", "approved", "149.90"),
    )

    assert result["verified_facts"]
    fact_names = {fact["name"] for fact in result["verified_facts"]}
    assert {"status", "amount", "currency"}.issubset(fact_names)
    assert "txn1001" in result["response"]


@pytest.mark.network
def test_customer_support_real_integration_settlement_lookup():
    _requires_real_ollama_integration()

    client = RecordingOllamaClient()
    agent = CustomerSupportAgent(client=client)

    result = agent.answer("Quando cai o dinheiro das vendas de ontem?", "cliente1988")

    assert result["agent"] == "customer_support"
    assert result["flow_completed"] is True
    assert result["response_delivered"] is True
    assert result["tool_used"] == "lookup_settlement"
    assert result["issue_resolved"] is True
    assert result["function_call_status"] == "tool_call_success"

    _assert_history_contains_tool_round(
        client,
        "lookup_settlement",
        expected_result_keywords=("settlement", "sale_date", "estimated_settlement_date"),
    )

    yesterday = (settlement_reference_date() - timedelta(days=1)).strftime("%d/%m/%Y")
    assert f"Prazo de recebimento das vendas de ontem ({yesterday})" in result["response"]
    assert "txn1001" in result["response"]
    assert "txn1002" not in result["response"]
