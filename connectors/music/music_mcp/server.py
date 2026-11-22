"""MCP-сервер music: музыка, радио и звук Mac на наших колонках (stdio).

Звук играет колонка (прошивка 0.6.0+), очередь ведёт ядро: коннектор только выбирает, что и где,
и зовёт API ядра. Колонка по умолчанию — та, с которой говорят (`_meta.device` вызова), иначе её
выбирает ядро.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Mapping

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from music_mcp.core import CoreApi
from music_mcp.library import Library
from music_mcp.music import Music, MusicError

# у действий: модель зовёт их сама, без просьбы (ход «включи свет на кухне» включил бы музыку)
ONLY_ASKED = " Только по прямой просьбе человека."
SPEAKER = " speaker — имя колонки из просьбы («на кухне» — «кухня»); не названа — пусто."


async def _answer(call: Awaitable[str]) -> str:
    """Ответ инструмента; MusicError — ошибка инструмента с русским текстом."""
    try:
        return await call
    except MusicError as error:
        raise ToolError(str(error)) from None


def _here(ctx: Context) -> str | None:
    """Колонка, с которой говорят: `_meta.device` вызова от ядра (нет — None)."""
    meta = ctx.request_context.meta
    device = meta.get("device") if meta is not None else None
    return device if isinstance(device, str) and device else None


def _add_play_tools(server: MCPServer, music: Music) -> None:
    @server.tool(
        name="speaker_music_play",
        description=(
            "Включает музыку из папок Mac на колонке Кузи. query — исполнитель, альбом, папка или "
            "песня (пусто — всё подряд); shuffle — вперемешку. Пример: «включи Кино на кухне» — "
            "query «Кино», speaker «кухня»." + SPEAKER + ONLY_ASKED
        ),
    )
    async def music_play(ctx: Context, query: str = "", speaker: str = "", shuffle: bool = False) -> str:
        return await _answer(music.play_files(query, speaker, shuffle, _here(ctx)))

    @server.tool(
        name="speaker_radio_play",
        description=(
            "Включает интернет-радио на колонке Кузи: station — название станции из настроек "
            "(пусто — первая). Пример: «включи джаз-радио»." + SPEAKER + ONLY_ASKED
        ),
    )
    async def radio_play(ctx: Context, station: str = "", speaker: str = "") -> str:
        return await _answer(music.play_radio(station, speaker, _here(ctx)))

    @server.tool(
        name="speaker_mac_audio_play",
        description=(
            "Включает на колонке Кузи звук Mac (Spotify, Яндекс Музыка, YouTube — всё, что Mac "
            "играет в BlackHole). Пример: «включи звук с Мака на кухне»." + SPEAKER + ONLY_ASKED
        ),
    )
    async def mac_audio_play(ctx: Context, speaker: str = "") -> str:
        return await _answer(music.play_mac(speaker, _here(ctx)))


def _add_control_tools(server: MCPServer, music: Music) -> None:
    actions = {
        "pause": "Пауза музыки на колонке Кузи. Пример: «поставь на паузу».",
        "resume": "Продолжает музыку на колонке Кузи с места паузы. Пример: «продолжи».",
        "next": "Следующий трек на колонке Кузи. Пример: «дальше», «следующая».",
        "previous": "Предыдущий трек на колонке Кузи. Пример: «назад», «предыдущая».",
        "stop": "Выключает музыку, радио или звук Mac на колонке Кузи. Пример: «выключи музыку».",
    }
    for action, text in actions.items():
        _add_control(server, music, action, text + SPEAKER + ONLY_ASKED)

    @server.tool(
        name="speaker_music_volume",
        description=(
            "Громкость музыки на колонке Кузи: percent — от 0 до 100 («громкость 30» — 30), или "
            "delta — на сколько процентов громче/тише («громче» — 10, «тише» — -10)." + SPEAKER + ONLY_ASKED
        ),
    )
    async def volume(delta: int = 0, percent: int = -1, speaker: str = "") -> str:
        return await _answer(music.volume(delta, percent, speaker))


def _add_control(server: MCPServer, music: Music, action: str, description: str) -> None:
    @server.tool(name=f"speaker_music_{action}", description=description)
    async def control(speaker: str = "") -> str:
        return await _answer(music.control(action, speaker))


def build_server(env: Mapping[str, str], transport: httpx.AsyncBaseTransport | None = None) -> MCPServer:
    """Сервер над настройками env (папки, станции, устройство, адрес ядра); transport — сеть (тесты)."""
    server = MCPServer("music")
    music = Music(Library(env), CoreApi(env, transport), transport)
    _add_play_tools(server, music)
    _add_control_tools(server, music)

    @server.tool(name="speaker_music_status", description="Что сейчас играет на колонках Кузи и где.")
    async def status() -> str:
        return await _answer(music.status())

    @server.tool(
        name="speaker_music_library",
        description="Какая музыка есть для колонок Кузи: папки, радиостанции, звук Mac.",
    )
    async def library() -> str:
        return music.library()

    return server


def main() -> None:
    """Точка входа `music-mcp`: запуск по stdio. Данных не хранит."""
    build_server(dict(os.environ)).run("stdio")
