"""MCP-сервер weather: погода сейчас и прогноз (Open-Meteo, stdio)."""

import os
from collections.abc import Mapping
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


class _Weather:
    """Место из окружения; название геокодируется один раз за запуск."""

    def __init__(self, env: Mapping[str, str], transport: httpx.AsyncBaseTransport | None) -> None:
        self._env = env
        self._transport = transport
        self._place: Place | None = None

    async def _resolve(self, client: httpx.AsyncClient) -> Place:
        if self._place is not None:
            return self._place
        lat, lon = self._env.get("WEATHER_LAT", ""), self._env.get("WEATHER_LON", "")
        name = self._env.get("WEATHER_PLACE", "").strip()
        if lat and lon:
            try:
                self._place = Place(float(lat), float(lon), name)
            except ValueError:
                raise ToolError(NO_PLACE) from None
        elif name:
            self._place = await geocode(client, name)
        else:
            raise ToolError(NO_PLACE)
        return self._place

    async def load(self) -> dict[str, Any]:
        """Данные Open-Meteo для места; любой сбой — ToolError с честным текстом."""
        try:
            async with make_client(self._transport) as client:
                place = await self._resolve(client)
                return await fetch_forecast(client, place)
        except WeatherError:
            raise ToolError(FAILURE) from None


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
        data = await weather.load()
        return now_phrase(data["current"])

    @server.tool(
        name="weather_forecast",
        description=(
            "Прогноз на день: мин и макс температура, осадки, ветер. day: сегодня, завтра, "
            "послезавтра, день недели («в пятницу») или «в выходные» (на неделю вперёд)."
        ),
    )
    async def weather_forecast(day: str = "сегодня") -> str:
        data = await weather.load()
        today = (
            datetime.fromisoformat(data["current"]["time"]).date()
            if "time" in data["current"]
            else date.today()
        )
        parsed = parse_day(day, today)
        if parsed is None:
            raise ToolError("Не понял, на какой день. Скажите: сегодня, завтра или день недели.")
        phrase = forecast_phrase(data["daily"], today, parsed)
        if phrase is None:
            raise ToolError("Прогноз есть только на неделю вперёд.")
        return phrase

    return server


def main() -> None:
    """Точка входа `weather-mcp`: запуск по stdio. Данных не хранит."""
    build_server().run("stdio")
