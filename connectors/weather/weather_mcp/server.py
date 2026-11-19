"""MCP-сервер weather: погода сейчас и прогноз (Open-Meteo, stdio)."""

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from datetime import date, datetime
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from weather_mcp.api import Place, WeatherError, fetch_forecast, geocode, make_client
from weather_mcp.days import parse_day
from weather_mcp.phrases import forecast_phrase, now_phrase

FAILURE = "Не получилось узнать погоду."
NO_PLACE = "Место не задано в настройках погоды."
BAD_COORDS = "Координаты в настройках погоды заданы неверно."

log = logging.getLogger("weather_mcp")


class _Weather:
    """Место из окружения; название геокодируется один раз за запуск."""

    def __init__(self, env: Mapping[str, str], transport: httpx.AsyncBaseTransport | None) -> None:
        self._env = env
        self._transport = transport
        self._place: Place | None = None
        self._prefix = ""

    async def _resolve(self, client: httpx.AsyncClient) -> Place:
        if self._place is not None:
            return self._place
        lat, lon = self._env.get("WEATHER_LAT", ""), self._env.get("WEATHER_LON", "")
        name = self._env.get("WEATHER_PLACE", "").strip()
        if lat and lon:
            try:
                place = Place(float(lat), float(lon), name)
            except ValueError:
                raise ToolError(BAD_COORDS) from None
        elif name:
            place = await geocode(client, name)
            asked = name.partition(",")[0].strip()
            if place.name.casefold() != asked.casefold():
                self._prefix = f"Место: {place.name}. "
            log.warning("weather place %r resolved to %r (%s, %s)", name, place.name, place.lat, place.lon)
        else:
            raise ToolError(NO_PLACE)
        self._place = place
        return place

    async def load(self) -> tuple[dict[str, Any], str]:
        """Данные Open-Meteo и приставка с местом (если оно отличается от заданного)."""
        try:
            async with make_client(self._transport) as client:
                place = await self._resolve(client)
                return await fetch_forecast(client, place), self._prefix
        except WeatherError as error:
            log.warning("weather request failed: %s", error)
            raise ToolError(FAILURE) from None


async def _guarded(action: Callable[[], Awaitable[str]]) -> str:
    """Любая неожиданная ошибка превращается в честный ответ; подробности — в лог."""
    try:
        return await action()
    except ToolError:
        raise
    except Exception:
        log.exception("weather tool failed")
        raise ToolError(FAILURE) from None


def _local_today(current: dict[str, Any]) -> date:
    try:
        return datetime.fromisoformat(current["time"]).date()
    except (KeyError, TypeError, ValueError):
        return date.today()


def build_server(
    env: Mapping[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> MCPServer:
    """Собирает сервер с двумя инструментами. env и transport — для тестов."""
    weather = _Weather(os.environ if env is None else env, transport)
    server = MCPServer("weather")

    @server.tool(
        name="weather_now",
        description=(
            "Погода сейчас в доме: температура, как ощущается, осадки, ветер. "
            "Вызывайте на «какая погода», «что на улице», «холодно ли»."
        ),
    )
    async def weather_now() -> str:
        async def action() -> str:
            data, prefix = await weather.load()
            return prefix + now_phrase(data["current"])

        return await _guarded(action)

    @server.tool(
        name="weather_forecast",
        description=(
            "Прогноз на день: мин и макс температура, осадки, ветер. day: сегодня, завтра, "
            "послезавтра, день недели («в пятницу») или «в выходные» (на неделю вперёд)."
        ),
    )
    async def weather_forecast(day: str = "сегодня") -> str:
        async def action() -> str:
            data, prefix = await weather.load()
            today = _local_today(data["current"])
            parsed = parse_day(day, today)
            if parsed is None:
                raise ToolError("Не понял, на какой день. Скажите: сегодня, завтра или день недели.")
            phrase = forecast_phrase(data["daily"], today, parsed)
            if phrase is None:
                raise ToolError("Прогноз есть только на неделю вперёд.")
            return prefix + phrase

        return await _guarded(action)

    return server


def main() -> None:
    """Точка входа `weather-mcp`: запуск по stdio. Данных не хранит."""
    build_server().run("stdio")
