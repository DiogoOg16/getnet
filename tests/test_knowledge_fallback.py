import requests

from app.agents.knowledge import KnowledgeAgent

QUESTION = "Como funciona a antecipação de recebíveis?"


def test_falls_back_to_retrieved_passages_when_llm_is_down(monkeypatch):
    def down(self, message, context):
        raise requests.ConnectionError("ollama indisponível")

    monkeypatch.setattr(KnowledgeAgent, "_generate", down)

    result = KnowledgeAgent().answer(QUESTION)

    assert result["tool_used"] == "retrieval_only"
    assert "não está disponível" in result["response"]
    assert result["sources"]
    assert result["sources"][0] in result["response"]
    assert "Não consegui gerar" not in result["response"]


def test_reports_llm_usage_when_available(monkeypatch):
    monkeypatch.setattr(
        KnowledgeAgent, "_generate", lambda self, m, c: "Resposta do modelo."
    )

    result = KnowledgeAgent().answer(QUESTION)

    assert result["tool_used"] == "ollama"
    assert result["response"] == "Resposta do modelo."
