"""Тесты инструментов через клиентскую сессию SDK в памяти; сеть — MockTransport."""

import os

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
    def __init__(self, fail: bool = False, geo: dict[str, object] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.fail = fail
        self.geo = GEO if geo is None else geo

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            raise httpx.ConnectError("offline")
        if "geocoding" in request.url.host:
            return httpx.Response(200, json=self.geo)
        return httpx.Response(200, json=FORECAST)


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
        "Завтра: небольшой дождь, от 1 до 5 градусов, осадки 2.5 мм, "
        "вероятность осадков 60 процентов, ветер до 6 метров в секунду."
    )


async def test_forecast_default_today_and_weekday() -> None:
    _, today = await call(Recorder(), "weather_forecast")
    assert today.startswith("Сегодня: пасмурно, от минус 4 до минус 1 градуса")
    _, friday = await call(Recorder(), "weather_forecast", {"day": "в субботу"})
    assert friday.startswith("В субботу: ясно")


async def test_forecast_weekend() -> None:
    _, text = await call(Recorder(), "weather_forecast", {"day": "в выходные"})
    assert text.startswith("В выходные: суббота: ясно")
    assert "воскресенье: пасмурно, от 2 до 4 градусов" in text


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


@pytest.mark.skipif(not os.environ.get("WEATHER_LIVE"), reason="WEATHER_LIVE не задан")
async def test_live_open_meteo() -> None:
    async with Client(build_server({"WEATHER_PLACE": "Москва"})) as client:
        result = await client.call_tool("weather_now", {})
    assert not result.is_error
