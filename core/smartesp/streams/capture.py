"""Звук Mac: устройство ввода AVFoundation (виртуальное BlackHole) как источник потока.

Источник «capture:<часть имени>» — первое устройство ввода, в имени которого есть эта часть (без
учёта регистра). Список устройств — `ffmpeg -f avfoundation -list_devices true -i ""` (stderr).
Звук с устройства ввода macOS отдаёт только с разрешения «Микрофон» тому, кто запустил ядро:
приложению SmartESP или терминалу. Без разрешения список бывает пуст.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable

CAPTURE_PREFIX = "capture:"
CAPTURE_TITLE = "Звук Mac"
LIST_TIMEOUT_S = 10.0
_SECTION = re.compile(r"AVFoundation (video|audio) devices:")
_DEVICE = re.compile(r"\]\s*\[(\d+)\]\s+(.+?)\s*$")

NO_FFMPEG = "Для звука Mac нужен ffmpeg (brew install ffmpeg)"
NO_INPUTS = (
    "macOS не показывает ядру устройства ввода. Разрешите доступ к микрофону: Системные настройки → "
    "Конфиденциальность и безопасность → Микрофон → SmartESP (или Терминал, если ядро запущено из него), "
    "и установите BlackHole: brew install --cask blackhole-2ch"
)
NOT_FOUND = (
    "Нет устройства ввода «{name}». Установите BlackHole (brew install --cask blackhole-2ch) или "
    "укажите имя устройства в настройках коннектора «Музыка на колонках». Есть: {known}"
)

type Probe = Callable[[str], Awaitable[str]]  # источник → почему не играть ("" — можно)


def parse_inputs(listing: str) -> list[tuple[int, str]]:
    """Устройства ввода звука из вывода -list_devices: (номер, имя)."""
    found: list[tuple[int, str]] = []
    section = ""
    for line in listing.splitlines():
        header = _SECTION.search(line)
        if header:
            section = header.group(1)
            continue
        device = _DEVICE.search(line)
        if device and section == "audio":
            found.append((int(device.group(1)), device.group(2)))
    return found


async def list_inputs(program: str) -> list[tuple[int, str]]:
    """Устройства ввода звука Mac (ffmpeg печатает список в stderr и выходит с ошибкой — так задумано)."""
    process = await asyncio.create_subprocess_exec(
        program,
        "-hide_banner",
        "-f",
        "avfoundation",
        "-list_devices",
        "true",
        "-i",
        "",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(LIST_TIMEOUT_S):
            _, errors = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        return []
    return parse_inputs(errors.decode(errors="replace"))


def match(inputs: list[tuple[int, str]], name: str) -> tuple[int, str] | None:
    """Первое устройство, в имени которого есть name (без учёта регистра)."""
    wanted = name.strip().casefold()
    return next((item for item in inputs if wanted in item[1].casefold()), None)


async def find_input(program: str, name: str) -> tuple[int, str] | None:
    """Устройство ввода по части имени или None."""
    return match(await list_inputs(program), name)


def input_names(find: Callable[[], str | None]) -> Callable[[], Awaitable[list[str]]]:
    """Имена устройств ввода Mac — для выбора «звука Mac» в настройках; нет ffmpeg — пусто."""

    async def names() -> list[str]:
        program = find()
        return [name for _, name in await list_inputs(program)] if program is not None else []

    return names


def capture_probe(find: Callable[[], str | None]) -> Probe:
    """Проверка источника перед игрой: для звука Mac — есть ли ffmpeg и устройство; прочее — можно."""

    async def probe(source: str) -> str:
        if not source.startswith(CAPTURE_PREFIX):
            return ""
        program = find()
        if program is None:
            return NO_FFMPEG
        name = source.removeprefix(CAPTURE_PREFIX)
        inputs = await list_inputs(program)
        if not inputs:
            return NO_INPUTS
        if match(inputs, name) is None:
            return NOT_FOUND.format(name=name, known=", ".join(n for _, n in inputs))
        return ""

    return probe
