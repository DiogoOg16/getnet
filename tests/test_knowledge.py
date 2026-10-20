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


def test_qr_code_pix_question_retrieves_qr_document():
    results = retrieve("Como vender via Pix por QR Code?")

    assert results
    assert any("QR Code" in result["title"] or "qr code" in result["title"].lower() for result in results)


def test_qr_code_question_answers_with_source_steps():
    result = KnowledgeAgent().answer("Como vender via Pix por QR Code?")

    assert result["agent"] == "knowledge"
    assert result["response"]
    content = result["response"].lower()
    assert "pix" in content
    assert "qr code" in content or "qr-code" in content or "qrcode" in content


def test_get_tap_habilitation_and_sale_answers_with_get_tap_steps():
    result = KnowledgeAgent().answer("Como habilitar e vender via Pix usando o Get Tap?")

    assert result["agent"] == "knowledge"
    content = result["response"].lower()
    assert "pix" in content
    assert "get tap" in content or "gettap" in content
    assert "habilitar" in content or "ativar" in content


def test_plugin_queries_return_platform_sections():
    results = retrieve("Quais plugins a Getnet trabalha?")

    assert results
    assert any(
        "VTEX" in result["title"] or "MAGENTO" in result["title"] or "SHOPIFY" in result["title"]
        for result in results
    )


def test_maquininha_error_lookup_returns_real_error_article():
    results = retrieve("Qual é o significado do erro ADQ 4-83 na maquininha?")

    assert results
    titles = "\n".join(result["title"] for result in results).lower()
    assert "adq 4-83" in titles or "4-83" in titles


def test_adq_483_returns_site_fix_steps():
    result = KnowledgeAgent().answer("Qual é o significado do erro ADQ 4-83 na maquininha?")

    assert result["agent"] == "knowledge"
    content = result["response"].lower()
    assert "erro adq 4-83" in content
    assert "tecla de função" in content
    assert "38" in content
    assert "inicialização" in content


@pytest.mark.parametrize(
    "query, required_terms",
    [
        ("Qual é o significado do erro ADQ 4-91 na maquininha?", ["erro adq 4-91", "tecla de função", "inicialização"]),
        ("Qual é o significado do erro ADQ 1-50 na maquininha?", ["erro adq 1-50", "tecla de função", "inicialização"]),
        ("Qual é o significado do erro IDL 1-08 na maquininha?", ["erro idl 1-08", "configuração", "apagar memória"]),
    ],
)
def test_maquininha_error_codes_return_real_site_steps(query, required_terms):
    result = KnowledgeAgent().answer(query)

    assert result["agent"] == "knowledge"
    content = result["response"].lower()
    for term in required_terms:
        assert term in content


def test_plugin_page_covers_plugins_question_with_domain_answer():
    result = KnowledgeAgent().answer("Com quais plugins digitais a Getnet trabalha?")

    assert result["agent"] == "knowledge"
    assert result["response"]
    content = result["response"].lower()
    assert "plugin" in content or "vtex" in content or "magento" in content or "shopify" in content


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


def test_sales_status_question_answers_with_documented_statuses():
    result = KnowledgeAgent().answer("Quais são os possíveis status das minhas vendas?")

    assert result["agent"] == "knowledge"
    content = result["response"].lower()
    assert "pré-autorizada" in content or "pre-autorizada" in content
    assert "autorizada" in content
    assert "negada" in content
    assert "cancelada" in content


def test_cadastro_question_answers_with_public_steps():
    result = KnowledgeAgent().answer("Como faço para cadastrar meu negócio no Getnet?")

    assert result["agent"] == "knowledge"
    content = result["response"].lower()
    assert "cadastro" in content or "cadastrar" in content
    assert "site getnet" in content or "portal" in content or "aplicativo" in content


def test_internet_troubleshooting_does_not_return_power_instructions():
    results = retrieve("Minha maquininha não conecta à internet, o que faço?")

    assert not any(
        result["title"] == "Como ligo ou desligo minha máquina?"
        for result in results
    )


def test_get_conta_estorno_and_config_queries_have_source_focused_answers():
    cases = [
        ("Como acesso a minha Get Conta?", ["aplicativo getnet", "portal"], "get conta"),
        ("Como realizo uma transferência e quais os limites diários?", ["transferência", "limite", "conta"], "get conta"),
        ("O que é tarifa de inatividade?", ["180 dias", "r$ 10", "inatividade"], "get conta"),
        ("Como estornar uma venda na maquininha Getnet?", ["estorno", "suporte", "maquininha"], "estorno"),
        ("O que é chargeback e como evitar?", ["chargeback", "venda", "banco"], "chargeback"),
        ("Como configurar o Wi-Fi na sua maquininha Getnet?", ["wi-fi", "wifi", "maquininha"], "wi-fi"),
        ("Como consultar minhas vendas?", ["aplicativo", "portal", "vendas"], "vendas"),
        ("Funcionalidades portal minha conta e App Getnet Brasil", ["portal", "aplicativo", "getnet"], "app"),
    ]

    for query, required_terms, keyword in cases:
        result = KnowledgeAgent().answer(query)
        assert result["agent"] == "knowledge"
        content = result["response"].lower()
        assert content
        for term in required_terms:
            assert term in content or term.replace("-", " ") in content


def test_anticipation_definition_ranks_before_secondary_details():
    results = retrieve("Como funciona a antecipação de recebíveis?")

    titles = [result["title"].lower() for result in results]
    definition = "o que é antecipação de vendas?"

    assert definition in titles
    assert titles.index(definition) == 0