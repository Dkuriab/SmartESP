"""MCP-сервер mac_media: звук и музыка на Mac (stdio).

Только узкие инструменты: произвольный AppleScript коннектор не выполняет.
"""

from collections.abc import Awaitable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mac_media_mcp.media import MediaError, MediaService
from mac_media_mcp.system import MediaSystem

# у действий: модель зовёт их сама, без просьбы (ход «поставь таймер» переключал звук)
ONLY_ASKED = " Только по прямой просьбе человека."


async def _answer(call: Awaitable[str]) -> str:
    """Ответ инструмента; MediaError — ошибка инструмента с русским текстом."""
    try:
        return await call
    except MediaError as error:
        raise ToolError(str(error)) from None


def _add_key_tools(server: MCPServer, media: MediaService) -> None:
    """Медиа-клавиши: работают с любым плеером."""

    @server.tool(
        name="media_play_pause",
        description="Пауза или продолжение музыки (медиа-клавиша, любой плеер). Пример: «поставь на паузу»."
        + ONLY_ASKED,
    )
    async def play_pause() -> str:
        return await _answer(media.press("play_pause"))

    @server.tool(name="media_next", description="Следующий трек (медиа-клавиша, любой плеер)." + ONLY_ASKED)
    async def next_track() -> str:
        return await _answer(media.press("next"))

    @server.tool(
        name="media_previous", description="Предыдущий трек (медиа-клавиша, любой плеер)." + ONLY_ASKED
    )
    async def previous_track() -> str:
        return await _answer(media.press("previous"))

    @server.tool(
        name="media_now_playing",
        description="Что сейчас играет в «Музыке» или Spotify: исполнитель и название.",
    )
    async def now_playing() -> str:
        return await _answer(media.now_playing())


def _add_volume_tools(server: MCPServer, media: MediaService) -> None:
    """Громкость выхода Mac."""

    @server.tool(name="volume_get", description="Текущая громкость Mac в процентах.")
    async def volume_get() -> str:
        return await _answer(media.volume_get())

    @server.tool(
        name="volume_set",
        description="Ставит громкость Mac: целое от 0 до 100 процентов. Пример: «громкость 30» — 30."
        + ONLY_ASKED,
    )
    async def volume_set(percent: int) -> str:
        return await _answer(media.volume_set(percent))

    @server.tool(
        name="volume_change",
        description=(
            "Громче или тише на delta процентов (от -100 до 100). "
            "Пример: «сделай погромче» — 10, «потише» — -10." + ONLY_ASKED
        ),
    )
    async def volume_change(delta: int) -> str:
        return await _answer(media.volume_change(delta))


def _add_output_tools(server: MCPServer, media: MediaService) -> None:
    """Устройства вывода звука."""

    @server.tool(
        name="output_devices",
        description="Список устройств вывода звука (динамики, Bluetooth-колонки, AirPlay) и какое сейчас.",
    )
    async def output_devices() -> str:
        return await _answer(media.output_devices())

    @server.tool(
        name="output_set",
        description=(
            "Переключает звук Mac на устройство по имени или его части. Пример: «JBL», «динамики». "
            "Имя колонки из строки «Колонка: …» — не устройство Mac." + ONLY_ASKED
        ),
    )
    async def output_set(name: str) -> str:
        return await _answer(media.output_set(name))


def build_server(system: MediaSystem) -> MCPServer:
    """Собирает сервер над системой Mac `system` (в тестах — подделка)."""
    server = MCPServer("mac_media")
    media = MediaService(system)
    _add_key_tools(server, media)
    _add_volume_tools(server, media)
    _add_output_tools(server, media)

    @server.tool(
        name="music_play",
        description=(
            "Ищет в медиатеке «Музыки» песню, исполнителя или альбом и включает. "
            "Пример: «включи Кино» — «Кино»." + ONLY_ASKED
        ),
    )
    async def music_play(query: str) -> str:
        return await _answer(media.music_play(query))

    return server


def main() -> None:
    """Точка входа `mac-media-mcp`: запуск по stdio. Данных не хранит."""
    from mac_media_mcp.mac import MacSystem

    build_server(MacSystem()).run("stdio")
