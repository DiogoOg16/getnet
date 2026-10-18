import re

import requests
from bs4 import BeautifulSoup
from app.tools.exchange_rate import (
    CURRENCIES,
    detect_currency,
    format_brl,
    get_exchange_rate,
)
from urllib.parse import parse_qs, unquote, urlparse


class WebSearchAgent:
    """Searches the public web and returns validated, sourced results."""

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    TIMEOUT = 8
    MAX_RESULTS = 5

    ALLOWED_DOMAINS = {
        "getnet.com.br",
        "bcb.gov.br",
        "gov.br",
        "ibge.gov.br",
        "inmet.gov.br",
        "ecb.europa.eu",
        "wikipedia.org",
        "lemonde.fr",
        "reuters.com",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
    }

    def answer(self, message: str) -> dict:
        currency = detect_currency(message)
        if currency and self._is_exchange_question(message):
            return self._exchange_answer(currency)

        try:
            response = requests.post(
                self.SEARCH_URL,
                data={"q": message},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 Chrome/130 Safari/537.36"
                    )
                },
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException:
            return self._unavailable(
                "Não foi possível acessar a busca na web neste momento."
            )

        soup = BeautifulSoup(response.text, "html.parser")
        result_elements = soup.select(".result")

        # A successful HTTP response does not guarantee that the search
        # engine returned a usable results page.
        if not result_elements:
            return self._unavailable(
                "O mecanismo de busca não retornou resultados utilizáveis."
            )

        results = []
        seen_urls = set()

        for item in result_elements:
            link = item.select_one(".result__a")
            snippet = item.select_one(".result__snippet")

            if not link or not link.get("href"):
                continue

            url = self._resolve_url(link["href"])
            if not url or not self._is_allowed_url(url):
                continue

            if url in seen_urls:
                continue
            seen_urls.add(url)

            results.append({
                "title": link.get_text(" ", strip=True),
                "url": url,
                "snippet": (
                    snippet.get_text(" ", strip=True)
                    if snippet
                    else ""
                ),
            })

            if len(results) >= self.MAX_RESULTS:
                break

        if not results:
            return {
                "agent": "web_search",
                "response": (
                    "A busca retornou resultados, mas nenhum passou "
                    "pela validação das fontes permitidas. Tente outra "
                    "consulta ou consulte uma fonte oficial."
                ),
                "sources": [],
                "tool_used": "duckduckgo_search",
            }

        formatted = "\n\n".join(
            f"{i}. {item['title']}\n"
            f"{item['snippet'] or 'O mecanismo não forneceu um resumo.'}\n"
            f"Fonte: {item['url']}"
            for i, item in enumerate(results, start=1)
        )

        return {
            "agent": "web_search",
            "response": (
                "Encontrei estes resultados na web. Os trechos são "
                "resumos do mecanismo de busca, não uma verificação "
                "independente do conteúdo das páginas. Para informações "
                "atuais ou decisões importantes, confirme os dados "
                "diretamente na fonte.\n\n"
                f"{formatted}"
            ),
            "sources": [item["url"] for item in results],
            "tool_used": "duckduckgo_search",
        }

    @staticmethod
    def _is_exchange_question(message: str) -> bool:
        return bool(re.search(
            r"cota[cç][aã]o|c[aâ]mbio|exchange rate|quanto (?:est[aá]|vale|custa)|how much",
            message.casefold(),
        ))

    @staticmethod
    def _exchange_answer(currency: str) -> dict:
        name = CURRENCIES[currency][0]
        result = get_exchange_rate(currency)

        if not result["found"]:
            reason = (
                "O serviço do Banco Central está indisponível no momento."
                if result["error"] == "unavailable"
                else "Não encontrei cotação recente nos últimos dias."
            )
            return {
                "agent": "web_search",
                "response": (
                    f"{reason} Consulte a cotação oficial em "
                    "https://www.bcb.gov.br/conversao."
                ),
                "sources": [],
                "tool_used": "bcb_ptax",
            }

        quoted_at = result["quoted_at"]
        return {
            "agent": "web_search",
            "response": (
                f"Cotação do {name} (PTAX de fechamento do Banco Central, "
                f"{quoted_at:%d/%m/%Y %H:%M}): compra "
                f"{format_brl(result['buy'])}, venda "
                f"{format_brl(result['sell'])}. Não é uma cotação em "
                "tempo real; bancos e casas de câmbio praticam valores "
                "diferentes."
            ),
            "sources": ["https://www.bcb.gov.br/conversao"],
            "tool_used": "bcb_ptax",
        }

    @staticmethod
    def _resolve_url(raw_url: str) -> str | None:
        """Unwrap DuckDuckGo redirects and accept only HTTP(S) URLs."""
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url

        parsed = urlparse(raw_url)

        if parsed.scheme not in {"http", "https"}:
            return None

        if parsed.hostname == "duckduckgo.com" or (
            parsed.hostname or ""
        ).endswith(".duckduckgo.com"):
            redirect = parse_qs(parsed.query).get("uddg", [None])[0]
            if not redirect:
                return None
            raw_url = unquote(redirect)
            parsed = urlparse(raw_url)

        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None

        return raw_url

    @classmethod
    def _is_allowed_url(cls, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
        return any(
            host == domain or host.endswith("." + domain)
            for domain in cls.ALLOWED_DOMAINS
        )

    @staticmethod
    def _unavailable(reason: str) -> dict:
        return {
            "agent": "web_search",
            "response": (
                f"{reason} Tente novamente mais tarde ou consulte "
                "uma fonte oficial."
            ),
            "sources": [],
            "tool_used": "duckduckgo_search",
        }
