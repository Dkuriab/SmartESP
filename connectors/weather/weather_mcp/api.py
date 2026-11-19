"""Запросы к Open-Meteo: геокодинг и прогноз. Любой сбой — WeatherError."""

from dataclasses import dataclass
from typing import Any

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
USER_AGENT = "SmartEsp-weather/0.1"
TIMEOUT_SECONDS = 5.0

_CURRENT = "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
_DAILY = (
    "temperature_2m_min,temperature_2m_max,precipitation_sum,"
    "precipitation_probability_max,weather_code,wind_speed_10m_max"
)


class WeatherError(Exception):
    """Не удалось получить данные (сеть, ответ сервиса, неизвестное место)."""


@dataclass(frozen=True)
class Place:
    """Координаты и название места."""

    lat: float
    lon: float
    name: str


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """HTTP-клиент с таймаутом 5 секунд и своим User-Agent."""
    return httpx.AsyncClient(timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}, transport=transport)


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise WeatherError(str(error)) from error
    if not isinstance(data, dict):
        raise WeatherError("unexpected response")
    return data  # pyright: ignore[reportUnknownVariableType]


async def geocode(client: httpx.AsyncClient, name: str) -> Place:
    """Находит место по названию; нет совпадений — WeatherError."""
    data = await _get_json(client, GEOCODING_URL, {"name": name, "language": "ru", "count": 1})
    results = data.get("results")
    if not results:
        raise WeatherError(f"place not found: {name}")
    first = results[0]
    try:
        return Place(float(first["latitude"]), float(first["longitude"]), str(first.get("name", name)))
    except (KeyError, TypeError, ValueError) as error:
        raise WeatherError("bad geocoding response") from error


async def fetch_forecast(client: httpx.AsyncClient, place: Place) -> dict[str, Any]:
    """Текущая погода и прогноз на 7 дней (время — местное для места)."""
    params: dict[str, Any] = {
        "latitude": place.lat,
        "longitude": place.lon,
        "current": _CURRENT,
        "daily": _DAILY,
        "wind_speed_unit": "ms",
        "forecast_days": 7,
        "timezone": "auto",
    }
    data = await _get_json(client, FORECAST_URL, params)
    if "current" not in data or "daily" not in data:
        raise WeatherError("bad forecast response")
    return data
