"""Exchange rates from the Banco Central do Brasil (PTAX), no API key."""

import re
import unicodedata
from datetime import date, datetime, timedelta

import requests

PTAX_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoMoedaDia(moeda=@moeda,dataCotacao=@dataCotacao)"
)
TIMEOUT = 15
MAX_LOOKBACK_DAYS = 7

CURRENCIES = {
    "EUR": ("euro", r"\beuros?\b"),
    "USD": ("dólar americano", r"\bdolar(?:es)?\b|\bdollars?\b|\busd\b"),
    "GBP": ("libra esterlina", r"\blibras?\b|\bpounds?\b|\bgbp\b"),
    "JPY": ("iene", r"\bienes?\b|\byen\b|\bjpy\b"),
    "ARS": ("peso argentino", r"\bpeso argentino\b|\bpesos argentinos\b|\bars\b"),
    "CHF": ("franco suíço", r"\bfrancos? suicos?\b|\bswiss franc\b|\bchf\b"),
    "CAD": ("dólar canadense", r"\bdolar canadense\b|\bcanadian dollar\b|\bcad\b"),
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def detect_currency(message: str) -> str | None:
    """Return the ISO code of the first currency mentioned, if any."""
    text = _normalize(message)
    # Variantes específicas (ex.: dólar canadense) antes das genéricas.
    for code in ("CAD", "CHF", "ARS", "EUR", "GBP", "JPY", "USD"):
        if re.search(CURRENCIES[code][1], text):
            return code
    return None


def _fetch_day(code: str, day: date) -> list[dict]:
    response = requests.get(
        PTAX_URL,
        params={
            "@moeda": f"'{code}'",
            "@dataCotacao": f"'{day.strftime('%m-%d-%Y')}'",
            "$format": "json",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("value", [])


def get_exchange_rate(code: str, today: date | None = None) -> dict:
    """Latest closing PTAX for a currency, stepping back over non-business days."""
    today = today or date.today()

    for offset in range(MAX_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=offset)
        try:
            bulletins = _fetch_day(code, day)
        except (requests.RequestException, ValueError):
            return {"found": False, "error": "unavailable"}

        closing = [
            b for b in bulletins
            if "fechamento" in b.get("tipoBoletim", "").casefold()
        ]
        if closing:
            bulletin = closing[-1]
            quoted_at = datetime.fromisoformat(
                bulletin["dataHoraCotacao"].split(".")[0]
            )
            return {
                "found": True,
                "currency": code,
                "buy": bulletin["cotacaoCompra"],
                "sell": bulletin["cotacaoVenda"],
                "quoted_at": quoted_at,
            }

    return {"found": False, "error": "no_quote"}


def format_brl(value: float) -> str:
    return f"R$ {value:,.4f}".replace(",", "X").replace(".", ",").replace("X", ".")
