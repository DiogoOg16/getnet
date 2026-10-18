import requests

from app.agents.web_search import WebSearchAgent


class FakeResponse:
    def __init__(self, text="", error=None):
        self.text = text
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error


def test_returns_only_allowed_domains(monkeypatch):
    html = """
    <div class="result">
      <a class="result__a"
         href="https://www.bcb.gov.br/conversao">Banco Central</a>
      <a class="result__snippet">Conversor oficial.</a>
    </div>
    <div class="result">
      <a class="result__a"
         href="https://example.com/fake">Site não permitido</a>
      <a class="result__snippet">Conteúdo qualquer.</a>
    </div>
    """

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeResponse(html),
    )

    result = WebSearchAgent().answer("cotação euro")

    assert len(result["sources"]) == 1
    assert result["sources"][0] == "https://www.bcb.gov.br/conversao"


def test_unavailable_when_request_fails(monkeypatch):
    def fail_request(*args, **kwargs):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "post", fail_request)

    result = WebSearchAgent().answer("cotação euro")

    assert result["agent"] == "web_search"
    assert result["sources"] == []
    assert "Não foi possível acessar" in result["response"]


def test_unavailable_when_results_page_is_unusable(monkeypatch):
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: FakeResponse(
            "<html><body>Search page unavailable</body></html>"
        ),
    )

    result = WebSearchAgent().answer("últimas notícias")

    assert result["sources"] == []
    assert "não retornou resultados utilizáveis" in result["response"]


def test_rejects_fake_domain():
    assert not WebSearchAgent._is_allowed_url(
        "https://bcb.gov.br.example.com/"
    )


def test_accepts_official_subdomain():
    assert WebSearchAgent._is_allowed_url(
        "https://www.bcb.gov.br/conversao"
    )


def test_unwraps_duckduckgo_redirect():
    url = (
        "https://duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fwww.bcb.gov.br%2Fconversao"
    )

    resolved = WebSearchAgent._resolve_url(url)

    assert resolved == "https://www.bcb.gov.br/conversao"


def test_unwraps_protocol_relative_duckduckgo_redirect():
    url = (
        "//duckduckgo.com/l/?uddg="
        "https%3A%2F%2Fwww.bcb.gov.br%2Fconversao"
    )

    assert (
        WebSearchAgent._resolve_url(url)
        == "https://www.bcb.gov.br/conversao"
    )
