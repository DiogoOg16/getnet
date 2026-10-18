from app.agents.knowledge import KnowledgeAgent
from app.rag.retriever import retrieve


def test_retrieves_pix_section():
    results = retrieve("Como funciona o Pix?")

    assert results
    assert any("Pix" in result["title"] for result in results)


def test_returns_sources_with_answer():
    result = KnowledgeAgent().answer("Quais informações existem sobre antecipação?")

    assert result["agent"] == "knowledge"
    assert result["response"]
    assert result["sources"]


def test_handles_empty_query():
    assert retrieve("") == []
