import requests

from app.tools.weather import extract_city, get_forecast, wants_tomorrow

GEO = {
    "results": [{
        "name": "Porto Alegre",
        "admin1": "Rio Grande do Sul",
        "country": "Brasil",
        "latitude": -30.03,
        "longitude": -51.23,
        "timezone": "America/Sao_Paulo",
    }]
}
FORECAST = {
    "daily": {
        "time": ["2026-10-18", "2026-10-19"],
        "temperature_2m_max": [18.3, 19.6],
        "temperature_2m_min": [11.4, 11.1],
        "precipitation_probability_max": [18, 10],
    }
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def fake_get(url, params, timeout):
    return FakeResponse(GEO if "geocoding" in url else FORECAST)


def test_extracts_city():
    assert extract_city("What's the weather forecast in Porto Alegre tomorrow?") == "Porto Alegre"
    assert extract_city("Como está o tempo em São Paulo hoje?") == "São Paulo"
    assert extract_city("Previsão do tempo para Rio de Janeiro") == "Rio de Janeiro"
    assert extract_city("Como está o clima?") is None


def test_detects_tomorrow():
    assert wants_tomorrow("weather tomorrow") is True
    assert wants_tomorrow("previsão para amanhã") is True
    assert wants_tomorrow("como está o tempo hoje") is False


def test_forecast_tomorrow(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get)

    result = get_forecast("Porto Alegre", tomorrow=True)

    assert result["found"] is True
    assert result["date"] == "2026-10-19"
    assert result["temp_max"] == 19.6
    assert result["rain_probability"] == 10


def test_forecast_today(monkeypatch):
    monkeypatch.setattr(requests, "get", fake_get)

    assert get_forecast("Porto Alegre")["date"] == "2026-10-18"


def test_city_not_found(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: FakeResponse({})
    )

    assert get_forecast("Xyzzyville") == {
        "found": False, "error": "city_not_found"
    }


def test_unavailable_when_request_fails(monkeypatch):
    def fail(*a, **k):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", fail)

    assert get_forecast("Porto Alegre") == {
        "found": False, "error": "unavailable"
    }
