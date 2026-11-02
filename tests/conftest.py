import json
import os
import re

import pytest

from app.agents import customer_support
from app.agents.knowledge import KnowledgeAgent
from app.main import handoff_store, orchestrator, session_memory


class FakeCustomerSupportOllamaClient:
    """Cliente Ollama determinístico para os testes comuns."""

    def chat(self, messages, tools=None):
        last_user_message = next(
            (
                message.get("content", "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )

        available_tools = {
            tool["function"]["name"]
            for tool in (tools or [])
            if isinstance(tool, dict)
            and isinstance(tool.get("function"), dict)
            and isinstance(tool["function"].get("name"), str)
        }

        # Depois da execução da ferramenta, o modelo encerra a interação.
        if any(message.get("role") == "tool" for message in messages):
            return {
                "message": {
                    "role": "assistant",
                    "content": "Consulta operacional concluída.",
                }
            }

        # Seleciona somente ferramentas que o backend autorizou.
        transaction_match = re.search(
            r"\btxn\d+\b",
            last_user_message,
            re.IGNORECASE,
        )

        if (
            transaction_match
            and "lookup_transaction" in available_tools
        ):
            tool_name = "lookup_transaction"
            arguments = {
                "transaction_id": transaction_match.group(0).lower()
            }
        elif "lookup_settlement" in available_tools:
            tool_name = "lookup_settlement"
            arguments = {}
        elif "lookup_customer" in available_tools:
            tool_name = "lookup_customer"
            arguments = {}
        else:
            return {
                "message": {
                    "role": "assistant",
                    "content": "Não há ferramenta autorizada para esta consulta.",
                }
            }

        return {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "test_call_1",
                        "function": {
                            "name": tool_name,
                            "arguments": arguments,
                        },
                    }
                ],
            }
        }


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Impede chamadas reais ao Ollama nos testes comuns."""

    def fake_generate(self, message, context):
        return "Resposta simulada baseada nos documentos recuperados."

    monkeypatch.setattr(KnowledgeAgent, "_generate", fake_generate)

    # Os testes de integração real precisam usar o Ollama verdadeiro.
    if os.getenv("RUN_OLLAMA_INTEGRATION") == "1":
        return

    fake_client = FakeCustomerSupportOllamaClient()

    # Novas instâncias de CustomerSupportAgent usarão o cliente falso.
    monkeypatch.setattr(
        customer_support,
        "OllamaClient",
        lambda: fake_client,
    )

    # Também substitui o cliente das instâncias já criadas por app.main.
    support = orchestrator.support

    monkeypatch.setattr(support, "client", fake_client)
    monkeypatch.setattr(support.loop, "client", fake_client)


@pytest.fixture(autouse=True)
def configure_demo_auth_tokens(monkeypatch):
    tokens = {
        "test-token-cliente1988": "cliente1988",
        "test-token-cliente2001": "cliente2001",
        "test-token-atendente_01": "atendente_01",
    }

    monkeypatch.setenv(
        "GETNET_DEMO_AUTH_TOKENS",
        json.dumps(tokens),
    )

    session_memory._store = {}
    session_memory.storage_path.unlink(missing_ok=True)

    handoff_store._records = {}
    handoff_store.storage_path.unlink(missing_ok=True)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: usa a internet; rode com RUN_NETWORK_TESTS=1"
    )


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_NETWORK_TESTS") == "1":
        return

    skip = pytest.mark.skip(
        reason="teste de rede; use RUN_NETWORK_TESTS=1"
    )

    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
