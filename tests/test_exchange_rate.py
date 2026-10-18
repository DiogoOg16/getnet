from datetime import date

import requests

from app.tools import exchange_rate
from app.tools.exchange_rate import (
    detect_currency,
    format_brl,
    get_exchange_rate,
)

CLOSING = {
    "cotacaoCompra": 5.7076,
    "cotacaoVenda": 5.7088,
    "dataHoraCotacao": "2026-10-16 13:04:14.548156",
    "tipoBoletim": "Fechamento PTAX",
}
OPENING = {
    "cotacaoCompra": 5.0,
    "cotacaoVenda": 5.1,
    "dataHoraCotacao": "2026-10-16 10:08:09.499681",
    "tipoBoletim": "Abertura",
}


class FakeResponse:
    def __init__(self, value):
        self._value = value

    def raise_for_status(self):
        pass

    def json(self):
        return {"value": self._value}


def test_detects_currencies():
    assert detect_currency("What's the euro exchange rate today?") == "EUR"
    assert detect_currency("Qual a cotação do dólar?") == "USD"
    assert detect_currency("cotação do dólar canadense") == "CAD"
    assert detect_currency("Meu neurologista atende?") is None


def test_uses_closing_bulletin(monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: FakeResponse([OPENING, CLOSING]),
    )

    result = get_exchange_rate("EUR", today=date(2026, 10, 16))

    assert result["found"] is True
    assert result["sell"] == 5.7088
    assert result["quoted_at"].date() == date(2026, 10, 16)


def test_steps_back_over_weekend(monkeypatch):
    queried = []

    def fake_get(url, params, timeout):
        queried.append(params["@dataCotacao"])
        if params["@dataCotacao"] == "'10-16-2026'":
            return FakeResponse([CLOSING])
        return FakeResponse([])

    monkeypatch.setattr(requests, "get", fake_get)

    # 18/10/2026 é domingo, 17 é sábado, 16 é sexta.
    result = get_exchange_rate("EUR", today=date(2026, 10, 18))

    assert result["found"] is True
    assert queried == ["'10-18-2026'", "'10-17-2026'", "'10-16-2026'"]


def test_no_quote_after_lookback(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse([]))

    result = get_exchange_rate("EUR", today=date(2026, 10, 18))

    assert result == {"found": False, "error": "no_quote"}


def test_unavailable_when_request_fails(monkeypatch):
    def fail(*a, **k):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", fail)

    result = get_exchange_rate("EUR", today=date(2026, 10, 18))

    assert result == {"found": False, "error": "unavailable"}


def test_format_brl():
    assert format_brl(5.7088) == "R$ 5,7088"
    assert exchange_rate.format_brl(1234.5) == "R$ 1.234,5000"
