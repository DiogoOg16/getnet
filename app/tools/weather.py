"""Weather forecasts from Open-Meteo (no API key)."""

import re
import unicodedata

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 15

_CITY_PATTERN = re.compile(
    r"\b(?:em|in|para|for|de|at)\s+"
    r"([A-ZÀ-Ý][\wÀ-ÿ'-]*(?:\s+(?:de|da|do|dos|das|of)?\s*[A-ZÀ-Ý][\wÀ-ÿ'-]*)*)"
)
_TOMORROW = re.compile(r"\bamanha\b|\btomorrow\b")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def extract_city(message: str) -> str | None:
    """Return a capitalized place name following em/in/para/for, if any."""
    match = _CITY_PATTERN.search(message)
    return match.group(1).strip() if match else None


def wants_tomorrow(message: str) -> bool:
    return bool(_TOMORROW.search(_normalize(message)))


def get_forecast(city: str, tomorrow: bool = False) -> dict:
    """Daily forecast for a city. Never invents values on failure."""
    try:
        geo = requests.get(
            GEOCODING_URL,
            params={"name": city, "count": 1, "language": "pt"},
            timeout=TIMEOUT,
        )
        geo.raise_for_status()
        results = geo.json().get("results") or []
        if not results:
            return {"found": False, "error": "city_not_found"}

        place = results[0]
        forecast = requests.get(
            FORECAST_URL,
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
                "timezone": place.get("timezone", "auto"),
                "forecast_days": 2,
            },
            timeout=TIMEOUT,
        )
        forecast.raise_for_status()
        daily = forecast.json()["daily"]
        index = 1 if tomorrow else 0

        return {
            "found": True,
            "city": place["name"],
            "region": place.get("admin1"),
            "country": place.get("country"),
            "date": daily["time"][index],
            "temp_max": daily["temperature_2m_max"][index],
            "temp_min": daily["temperature_2m_min"][index],
            "rain_probability": daily["precipitation_probability_max"][index],
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return {"found": False, "error": "unavailable"}
