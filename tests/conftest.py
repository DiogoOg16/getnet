import json
import os

import pytest

from app.agents.knowledge import KnowledgeAgent
from app.main import handoff_store, session_memory


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Nenhum teste deve chamar o Ollama de verdade."""

    def fake_generate(self, message, context):
        return "Resposta simulada baseada nos documentos recuperados."

    monkeypatch.setattr(KnowledgeAgent, "_generate", fake_generate)


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

    skip = pytest.mark.skip(reason="teste de rede; use RUN_NETWORK_TESTS=1")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
