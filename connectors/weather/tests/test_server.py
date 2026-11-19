"""Тесты инструментов через клиентскую сессию SDK в памяти; сеть — MockTransport."""

import os
from collections.abc import Mapping

import httpx
import pytest
from mcp import Client
from mcp.types import TextContent

from weather_mcp.server import build_server

CURRENT = {
    "time": "2026-11-19T21:40",
    "temperature_2m": -3.2,
    "apparent_temperature": -7.6,
    "precipitation": 0.0,
    "weather_code": 3,
    "wind_speed_10m": 4.2,
}
DAILY = {
    "time": [f"2026-11-{19 + i}" for i in range(7)],
    "temperature_2m_min": [-4.0, 1.2, 0.0, 2.0, 3.0, -1.0, -2.0],
    "temperature_2m_max": [-1.0, 5.4, 0.2, 4.0, 6.0, 1.0, 0.0],
    "precipitation_sum": [0.0, 2.5, 0.0, 0.0, 0.0, 0.0, 0.0],
    "precipitation_probability_max": [10, 60, 0, 5, 5, 5, 5],
    "weather_code": [3, 61, 0, 3, 3, 73, 71],
    "wind_speed_10m_max": [5.0, 6.4, 0.2, 3.0, 3.0, 3.0, 3.0],
}
FORECAST = {"current": CURRENT, "daily": DAILY}
GEO = {"results": [{"name": "Москва", "latitude": 55.75, "longitude": 37.62}]}


class Recorder:
    def __init__(
        self,
        fail: bool = False,
        geo: dict[str, object] | None = None,
        forecast: Mapping[str, object] | None = None,
    ) -> None:
        self.forecast = FORECAST if forecast is None else forecast
        self.requests: list[httpx.Request] = []
        self.fail = fail
        self.geo = GEO if geo is None else geo

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("offline")
        if "geocoding" in request.url.host:
            return httpx.Response(200, json=self.geo)
        return httpx.Response(200, json=self.forecast)


async def call(
    recorder: Recorder, name: str, args: dict[str, object] | None = None, env: dict[str, str] | None = None
) -> tuple[bool, str]:
    env = {"WEATHER_PLACE": "Москва"} if env is None else env
    server = build_server(env, httpx.MockTransport(recorder))
    async with Client(server) as client:
        result = await client.call_tool(name, args or {})
    block = result.content[0]
    assert isinstance(block, TextContent)
    return result.is_error, block.text


async def test_tools_listed_in_russian() -> None:
    async with Client(build_server({}, httpx.MockTransport(Recorder()))) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {"weather_now", "weather_forecast"}
    for tool in tools:
        assert tool.description
        assert any("а" <= ch.lower() <= "я" for ch in tool.description)


async def test_now_with_geocoded_place() -> None:
    recorder = Recorder()
    is_error, text = await call(recorder, "weather_now")
    assert not is_error
    assert (
        text == "Сейчас пасмурно, минус 3 градуса, ощущается как минус 8 градусов, ветер 4 метра в секунду."
    )
    geo, forecast = recorder.requests
    assert geo.url.params["name"] == "Москва"
    assert geo.url.params["language"] == "ru"
    assert forecast.url.params["latitude"] == "55.75"
    assert forecast.url.params["timezone"] == "auto"
    assert forecast.headers["user-agent"] == "SmartEsp-weather/0.1"


async def test_coordinates_skip_geocoding() -> None:
    recorder = Recorder()
    env = {"WEATHER_LAT": "59.9", "WEATHER_LON": "30.3"}
    is_error, _ = await call(recorder, "weather_now", env=env)
    assert not is_error
    assert len(recorder.requests) == 1
    assert recorder.requests[0].url.params["longitude"] == "30.3"


async def test_forecast_tomorrow() -> None:
    is_error, text = await call(Recorder(), "weather_forecast", {"day": "завтра"})
    assert not is_error
    assert text == (
        "Завтра: небольшой дождь, от 1 до 5 градусов, осадки 2,5 миллиметра, "
        "вероятность осадков 60 процентов, ветер до 6 метров в секунду."
    )


async def test_forecast_default_today_and_weekday() -> None:
    _, today = await call(Recorder(), "weather_forecast")
    assert today.startswith("Сегодня: пасмурно, от минус 4 до минус 1 градуса")
    _, friday = await call(Recorder(), "weather_forecast", {"day": "в субботу"})
    assert friday.startswith("В субботу: ясно")


async def test_forecast_weekend() -> None:
    _, text = await call(Recorder(), "weather_forecast", {"day": "в выходные"})
    assert text.startswith("В выходные: в субботу ясно")
    assert "в воскресенье пасмурно, от 2 до 4 градусов" in text


async def test_unknown_day() -> None:
    is_error, text = await call(Recorder(), "weather_forecast", {"day": "когда-нибудь"})
    assert is_error
    assert "не понял" in text.lower()


async def test_network_failure_is_honest() -> None:
    is_error, text = await call(Recorder(fail=True), "weather_now")
    assert is_error
    assert text.endswith("Не получилось узнать погоду.")


async def test_unknown_place_is_failure() -> None:
    is_error, text = await call(Recorder(geo={"results": []}), "weather_now")
    assert is_error
    assert text.endswith("Не получилось узнать погоду.")


async def test_no_place_configured() -> None:
    recorder = Recorder()
    is_error, text = await call(recorder, "weather_now", env={})
    assert is_error
    assert "место" in text.lower()
    assert recorder.requests == []


async def test_geocoding_cached_between_calls() -> None:
    recorder = Recorder()
    server = build_server({"WEATHER_PLACE": "Москва"}, httpx.MockTransport(recorder))
    async with Client(server) as client:
        await client.call_tool("weather_now", {})
        await client.call_tool("weather_now", {})
    assert sum("geocoding" in r.url.host for r in recorder.requests) == 1


def _forecast(
    current: dict[str, object] | None = None, daily: dict[str, object] | None = None
) -> dict[str, object]:
    return {"current": {**CURRENT, **(current or {})}, "daily": {**DAILY, **(daily or {})}}


async def test_null_fields_are_omitted() -> None:
    recorder = Recorder(forecast=_forecast({"apparent_temperature": None, "weather_code": None}))
    is_error, text = await call(recorder, "weather_now")
    assert not is_error
    assert text == "Сейчас минус 3 градуса, ветер 4 метра в секунду."


async def test_missing_current_temperature_is_failure() -> None:
    forecast = _forecast({"temperature_2m": None})
    is_error, text = await call(Recorder(forecast=forecast), "weather_now")
    assert is_error
    assert text.endswith("Не получилось узнать погоду.")


async def test_null_daily_fields() -> None:
    daily: dict[str, object] = {
        "temperature_2m_min": [None] * 7,
        "precipitation_sum": [None] * 7,
        "precipitation_probability_max": [None] * 7,
        "wind_speed_10m_max": [None] * 7,
    }
    _, text = await call(Recorder(forecast=_forecast(daily=daily)), "weather_forecast", {"day": "завтра"})
    assert text == "Завтра: небольшой дождь, максимум 5 градусов."


async def test_empty_day_is_failure() -> None:
    nulls: dict[str, object] = {k: [None] * 7 for k in DAILY if k != "time"}
    is_error, text = await call(Recorder(forecast=_forecast(daily=nulls)), "weather_forecast")
    assert is_error
    assert text.endswith("Не получилось узнать погоду.")


@pytest.mark.parametrize(
    "forecast",
    [
        {"current": {"time": "2026-11-19T21:40"}, "daily": {"time": ["2026-11-19"]}},
        {"current": CURRENT, "daily": {"time": ["не дата"]}},
        {"current": CURRENT, "daily": {"time": None}},
        {"current": [], "daily": {}},
    ],
)
async def test_garbage_response_is_honest(forecast: dict[str, object]) -> None:
    is_error, text = await call(Recorder(forecast=forecast), "weather_forecast")
    assert is_error
    assert text.endswith("Не получилось узнать погоду.")


def _geo(*items: tuple[str, str, int | None, float]) -> dict[str, object]:
    return {
        "results": [
            {
                "name": "Кировск",
                "country": country,
                "country_code": code,
                "population": population,
                "latitude": lat,
                "longitude": 30.0,
            }
            for country, code, population, lat in items
        ]
    }


async def test_geocoding_prefers_russia_then_population() -> None:
    geo = _geo(("Беларусь", "BY", 99999, 1.0), ("Россия", "RU", 5, 2.0), ("Россия", "RU", 500, 3.0))
    recorder = Recorder(geo=geo)
    is_error, text = await call(recorder, "weather_now", env={"WEATHER_PLACE": "Кировск"})
    assert not is_error
    assert recorder.requests[0].url.params["count"] == "10"
    assert recorder.requests[1].url.params["latitude"] == "3.0"
    assert text.startswith("Сейчас")


async def test_geocoding_falls_back_to_most_populous_abroad() -> None:
    geo = _geo(("Беларусь", "BY", 10, 1.0), ("Украина", "UA", 900, 2.0))
    recorder = Recorder(geo=geo)
    await call(recorder, "weather_now", env={"WEATHER_PLACE": "Кировск"})
    assert recorder.requests[1].url.params["latitude"] == "2.0"


@pytest.mark.parametrize("hint", ["Беларусь", "беларусь", "by"])
async def test_geocoding_city_comma_country(hint: str) -> None:
    geo = _geo(("Россия", "RU", 500, 3.0), ("Беларусь", "BY", 10, 1.0))
    recorder = Recorder(geo=geo)
    await call(recorder, "weather_now", env={"WEATHER_PLACE": f"Кировск, {hint}"})
    assert recorder.requests[0].url.params["name"] == "Кировск"
    assert recorder.requests[1].url.params["latitude"] == "1.0"


async def test_geocoding_unknown_country_hint_is_failure() -> None:
    recorder = Recorder(geo=_geo(("Россия", "RU", 500, 3.0)))
    is_error, text = await call(recorder, "weather_now", env={"WEATHER_PLACE": "Кировск, Чили"})
    assert is_error
    assert text.endswith("Не получилось узнать погоду.")


async def test_resolved_name_only_when_differs() -> None:
    _, same = await call(Recorder(), "weather_now")  # «Москва» -> «Москва»
    assert not same.startswith("Место")
    geo: dict[str, object] = {"results": [{"name": "Санкт-Петербург", "latitude": 59.9, "longitude": 30.3}]}
    _, other = await call(Recorder(geo=geo), "weather_now", env={"WEATHER_PLACE": "Питер"})
    assert other.startswith("Место: Санкт-Петербург. Сейчас")


async def test_bad_coordinates_message() -> None:
    is_error, text = await call(Recorder(), "weather_now", env={"WEATHER_LAT": "x", "WEATHER_LON": "1"})
    assert is_error
    assert "неверно" in text


async def test_day_with_part_of_day() -> None:
    _, text = await call(Recorder(), "weather_forecast", {"day": "завтра вечером"})
    assert text.startswith("Завтра:")


@pytest.mark.skipif(not os.environ.get("WEATHER_LIVE"), reason="WEATHER_LIVE не задан")
async def test_live_open_meteo() -> None:
    async with Client(build_server({"WEATHER_PLACE": "Москва"})) as client:
        result = await client.call_tool("weather_now", {})
    assert not result.is_error
