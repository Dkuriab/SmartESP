"""Источник потока: проверка и разбор ffmpeg в PCM.

Источник — полный путь к звуковому файлу, ссылка http(s) (радио) или «capture:<часть имени>» —
звук Mac с устройства ввода (BlackHole), см. capture.py. Файл разбирается с перемоткой (-ss) и
только своими форматами; ссылка — живой поток с переподключением, без протокола file: плейлист HLS
не дотянется до файлов Mac.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Callable
from pathlib import Path
from urllib.parse import unquote, urlsplit

from smartesp.contracts import STREAM_RATE

from .capture import CAPTURE_PREFIX, CAPTURE_TITLE, find_input

_log = logging.getLogger(__name__)

AUDIO_SUFFIXES = frozenset(
    {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".oga", ".opus", ".aif", ".aiff"}
)
FILE_FORMATS = "mp3,mov,aac,flac,wav,ogg,aiff"  # mov — разборщик M4A
LIVE_FORMATS = "mp3,aac,ogg,hls,mpegts,mov,flac,wav"
LIVE_PROTOCOLS = "http,https,tcp,tls,crypto"
CHUNK_BYTES = 8 * 1024  # кусок PCM (0,25 с при 16 кГц, 0,08 с при 48 кГц)
FIRST_CHUNK_S = 12.0  # дольше первый звук не ждём (радио подключается секунды); колонка ждёт 20 с
MAX_SOURCE = 2048
MAX_DEVICE_NAME = 100

type Decode = Callable[[str, float, int], AsyncGenerator[bytes]]  # (источник, с секунды, частота) → PCM


def is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def is_capture(source: str) -> bool:
    return source.startswith(CAPTURE_PREFIX)


def is_live(source: str) -> bool:
    """Живой поток (радио, звук Mac): перемотки нет, «продолжить» начинает заново."""
    return is_url(source) or is_capture(source)


def check_source(source: str) -> str:
    """Почему источник не годится ("" — годится); есть ли устройство ввода — проверяет capture.probe."""
    if not source or len(source) > MAX_SOURCE or any(c in source for c in "\0\r\n"):
        return "Пустой или слишком длинный источник"
    if is_url(source):
        return "" if urlsplit(source).hostname else f"Неверная ссылка: {source}"
    if is_capture(source):
        name = source.removeprefix(CAPTURE_PREFIX).strip()
        return "" if 0 < len(name) <= MAX_DEVICE_NAME else "Нужно имя устройства ввода (например, BlackHole)"
    path = Path(source)
    if not path.is_absolute():
        return f"Нужен полный путь к файлу или ссылка http(s): {source}"
    if path.suffix.lower() not in AUDIO_SUFFIXES:
        return f"Не звуковой файл: {path.name}"
    if not path.is_file():
        return f"Нет файла: {path.name}"
    return ""


def title_of(source: str) -> str:
    """Название по умолчанию: имя файла без расширения, адрес станции или «Звук Mac»."""
    if is_capture(source):
        return CAPTURE_TITLE
    if is_url(source):
        parts = urlsplit(source)
        return unquote(parts.hostname or source) + unquote(parts.path if parts.path != "/" else "")
    return Path(source).stem


def arguments(program: str, source: str, start_s: float, rate: int = STREAM_RATE) -> list[str]:
    """Команда ffmpeg: источник → PCM s16le моно rate в stdout. У capture source — уже
    «capture:<номер устройства>» (номер находит find_input)."""
    head = [program, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if is_capture(source):
        index = source.removeprefix(CAPTURE_PREFIX)
        head += ["-format_whitelist", "avfoundation", "-f", "avfoundation", "-i", f":{index}"]
    elif is_url(source):
        head += ["-protocol_whitelist", LIVE_PROTOCOLS, "-format_whitelist", LIVE_FORMATS]
        head += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", source]
    else:
        head += ["-protocol_whitelist", "file", "-format_whitelist", FILE_FORMATS]
        head += ["-ss", f"{max(start_s, 0.0):.3f}", "-i", f"file:{source}"]
    return [*head, "-vn", "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", str(rate), "pipe:1"]


def ffmpeg_decoder(find: Callable[[], str | None]) -> Decode:
    """Разбор через ffmpeg (find() — путь к программе или None: тогда поток сразу кончается)."""

    async def decode(source: str, start_s: float, rate: int = STREAM_RATE) -> AsyncGenerator[bytes]:
        program = find()
        if program is None:
            _log.warning("Поток: нет ffmpeg (brew install ffmpeg)")
            return
        if is_capture(source):
            found = await find_input(program, source.removeprefix(CAPTURE_PREFIX))
            if found is None:
                _log.warning("Поток: нет устройства ввода «%s»", source.removeprefix(CAPTURE_PREFIX))
                return
            source = f"{CAPTURE_PREFIX}{found[0]}"
        process = await asyncio.create_subprocess_exec(
            *arguments(program, source, start_s, rate),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        draining = asyncio.create_task(_drain(process, source))
        try:
            assert process.stdout is not None
            tail = b""
            while data := await process.stdout.read(CHUNK_BYTES):
                data, tail = _whole(tail + data)
                if data:
                    yield data
        finally:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            await process.wait()
            await asyncio.gather(draining, return_exceptions=True)

    return decode


def _whole(data: bytes) -> tuple[bytes, bytes]:
    """(целые отсчёты, нечётный хвост)."""
    cut = len(data) & ~1
    return data[:cut], data[cut:]


async def _drain(process: asyncio.subprocess.Process, source: str) -> None:
    """Читает stderr ffmpeg (иначе он встанет); последнее — в журнал."""
    assert process.stderr is not None
    tail = b""
    while data := await process.stderr.read(4096):
        tail = (tail + data)[-500:]
    if tail:
        _log.warning("ffmpeg, поток %s: %s", title_of(source), tail.decode(errors="replace").strip())
