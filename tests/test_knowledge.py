import pytest

from app.agents.knowledge import KnowledgeAgent
from app.rag.retriever import retrieve


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    def fake_generate(self, message, context):
        return "Resposta simulada baseada nos documentos recuperados."

    monkeypatch.setattr(KnowledgeAgent, "_generate", fake_generate)


def test_retrieves_pix_section():
    results = retrieve("Como funciona o Pix?")

    assert results
    assert any("Pix" in result["title"] for result in results)


def test_returns_sources_with_answer():
    result = KnowledgeAgent().answer("Quais informações existem sobre antecipação?")

    assert result["agent"] == "knowledge"
    assert result["response"]
    assert result["sources"]


def test_answer_is_direct_for_pix_procedures():
    result = KnowledgeAgent().answer(
        "Como funciona o Pix na maquininha Getnet?"
    )

    assert result["agent"] == "knowledge"
    assert result["response"]
    assert any(
        "Pix na maquininha" in title
        for title in result["sources"]
    )

def test_get_tap_pix_question_retrieves_relevant_article():
    results = retrieve("Como habilitar e vender via Pix usando o Get Tap?")

    assert results
    assert any("Get Tap" in result["title"] for result in results)


def test_plugin_queries_return_platform_sections():
    results = retrieve("Quais plugins a Getnet trabalha?")

    assert results
    assert any(
        "VTEX" in result["title"] or "MAGENTO" in result["title"] or "SHOPIFY" in result["title"]
        for result in results
    )


def test_plugins_page_keeps_platform_feature_lists():
    from app.rag.ingest import ingest_source

    records = ingest_source({
        "url": "https://site.getnet.com.br/get-ajuda-ecommerce/plugins-digitais-que-a-getnet-trabalha/",
        "category": "customer_faq",
    })

    assert any(record["title"] == "2. MAGENTO" for record in records)
    assert any("API V1" in record["content"] and "Pix" in record["content"] for record in records)


def test_handles_empty_query():
    assert retrieve("") == []

def test_declined_transaction_retrieves_sales_status_not_pix_key_claim():
    results = retrieve("Por que minha transação foi recusada?")

    titles = [result["title"] for result in results]

    assert any("possíveis status das minhas vendas" in title.lower()
               for title in titles)
    assert not any("chave foi reivindicada" in title.lower()
                   for title in titles)


def test_sales_status_query_retrieves_relevant_document():
    results = retrieve("Quais são os possíveis status das minhas vendas?")

    assert results
    assert any("possíveis status das minhas vendas" in result["title"].lower()
               for result in results)


def test_internet_troubleshooting_does_not_return_power_instructions():
    results = retrieve("Minha maquininha não conecta à internet, o que faço?")

    assert not any(
        result["title"] == "Como ligo ou desligo minha máquina?"
        for result in results
    )


def test_anticipation_definition_ranks_before_secondary_details():
    results = retrieve("Como funciona a antecipação de recebíveis?")

    titles = [result["title"].lower() for result in results]
    definition = "o que é antecipação de vendas?"

    assert definition in titles
    assert titles.index(definition) == 0