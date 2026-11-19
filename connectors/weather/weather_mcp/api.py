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


def _split_place(query: str) -> tuple[str, str]:
    """«Город, Страна» -> («Город», «страна»); без запятой страна пустая."""
    city, _, country = query.partition(",")
    return city.strip(), country.strip().casefold()


def _pick(results: list[dict[str, Any]], country: str) -> dict[str, Any] | None:
    """Выбор места: названная страна, иначе Россия; среди них самое людное."""

    def matches(item: dict[str, Any], wanted: str) -> bool:
        code = str(item.get("country_code", "")).casefold()
        return wanted in (code, str(item.get("country", "")).casefold())

    pool = [item for item in results if matches(item, country)] if country else []
    if country and not pool:
        return None
    if not pool:
        pool = [item for item in results if matches(item, "ru")] or results
    if not pool:
        return None
    return max(pool, key=lambda item: item.get("population") or 0)


async def geocode(client: httpx.AsyncClient, query: str) -> Place:
    """Находит место по «Город» или «Город, Страна»; нет совпадений — WeatherError."""
    city, country = _split_place(query)
    data = await _get_json(client, GEOCODING_URL, {"name": city, "language": "ru", "count": 10})
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise WeatherError(f"place not found: {query}")
    chosen = _pick([item for item in results if isinstance(item, dict)], country)  # pyright: ignore[reportUnknownVariableType]
    if chosen is None:
        raise WeatherError(f"place not found: {query}")
    try:
        return Place(float(chosen["latitude"]), float(chosen["longitude"]), str(chosen.get("name", city)))
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
