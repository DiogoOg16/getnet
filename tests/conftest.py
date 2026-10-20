import os

import pytest

from app.agents.knowledge import KnowledgeAgent


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    """Nenhum teste deve chamar o Ollama de verdade."""

    def fake_generate(self, message, context):
        return "Resposta simulada baseada nos documentos recuperados."

    monkeypatch.setattr(KnowledgeAgent, "_generate", fake_generate)


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
