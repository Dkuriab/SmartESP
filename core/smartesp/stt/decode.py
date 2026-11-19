"""Разбор звука через ffmpeg → PCM s16le 16 кГц моно: голосовое для распознавания (OGG/Opus, WAV)
и звуковой файл для проигрывания на колонке (MP3, WAV, OGG, M4A, FLAC — по ходу, кусками).

ffmpeg ищется в PATH, затем в обычных местах Homebrew: приложение запускает ядро с
коротким PATH, где /opt/homebrew/bin может не быть.
"""

import asyncio
import contextlib
import logging
import os
import shutil
from collections import deque
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from pathlib import Path

from smartesp.contracts import SAMPLE_RATE, AskUnavailable, AudioUndecodable

_log = logging.getLogger(__name__)

FFMPEG_PLACES = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
DECODE_TIMEOUT_S = 10.0  # дольше разбор не ждём (обычно — доли секунды)
MAX_DURATION_S = 120  # длиннее — обрезаем: распознавание держит модель, а ход — не дольше 55 с
NO_FFMPEG = "Для голосовых сообщений нужен ffmpeg (brew install ffmpeg)"
UNDECODABLE = "Не получилось разобрать звук: нужен OGG/Opus или WAV"
VOICE_FORMATS = "ogg,wav"  # голосовое: форматы договора /ask/voice
FILE_FORMATS = "mp3,wav,ogg,mov,flac"  # файл: mov — разборщик M4A/MP4
FILE_MAX_DURATION_S = 15 * 60  # длиннее — обрезаем
FILE_CHUNK_BYTES = 32 * 1024  # кусок PCM из файла (1 с звука)
FILE_UNDECODABLE = "Не получилось разобрать файл: нужен MP3, WAV, OGG, M4A или FLAC"
FILE_SILENT = "В файле нет звука"
ERRORS_TAIL = 500  # сколько последних байтов ошибок ffmpeg помнить для журнала


def find_ffmpeg(places: Sequence[str] = FFMPEG_PLACES) -> str | None:
    """Путь к ffmpeg: из PATH, иначе первое исполняемое из places; нигде нет — None."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    return next((place for place in places if os.access(place, os.X_OK)), None)


async def decode_audio(
    data: bytes, *, ffmpeg: str | None = None, timeout_s: float = DECODE_TIMEOUT_S
) -> bytes:
    """Звук в PCM s16le, 16 кГц, моно (не длиннее MAX_DURATION_S); тишина без отсчётов — b"".

    ffmpeg — путь к программе (None — find_ffmpeg). Нет ffmpeg — AskUnavailable;
    звук не разобрать или разбор дольше timeout_s — AudioUndecodable.
    """
    program = ffmpeg or find_ffmpeg()
    if program is None:
        raise AskUnavailable(NO_FFMPEG)
    try:
        process = await asyncio.create_subprocess_exec(
            *_arguments(program, "pipe", VOICE_FORMATS, "pipe:0", MAX_DURATION_S),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        raise AskUnavailable(f"{NO_FFMPEG}: {error}") from error
    try:
        async with asyncio.timeout(timeout_s):
            pcm, errors = await process.communicate(data)
    except TimeoutError as error:
        raise AudioUndecodable(f"{UNDECODABLE} (разбор дольше {timeout_s:g} с)") from error
    finally:
        if process.returncode is None:  # срок или отмена: программу не оставляем
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if process.returncode != 0:
        _log.warning(
            "ffmpeg не разобрал звук (%d байт): %s", len(data), errors.decode(errors="replace")[-500:]
        )
        raise AudioUndecodable(UNDECODABLE)
    return pcm[: len(pcm) & ~1]


async def decode_file(
    path: Path, *, ffmpeg: str | None = None, timeout_s: float = DECODE_TIMEOUT_S
) -> AsyncGenerator[bytes]:
    """Звуковой файл в PCM s16le, 16 кГц, моно по ходу разбора (не длиннее FILE_MAX_DURATION_S).

    Куски — целые отсчёты. Ошибки — до первого куска: нет ffmpeg — AskUnavailable; файл не
    разобрать, в нём нет звука или первый кусок дольше timeout_s — AudioUndecodable. Сбой
    посреди файла заканчивает поток (пишется в журнал). Закрытие генератора останавливает ffmpeg.
    """
    program = ffmpeg or find_ffmpeg()
    if program is None:
        raise AskUnavailable(NO_FFMPEG)
    arguments = _arguments(program, "file", FILE_FORMATS, f"file:{path}", FILE_MAX_DURATION_S)
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as error:
        raise AskUnavailable(f"{NO_FFMPEG}: {error}") from error
    errors: deque[bytes] = deque()
    draining = asyncio.create_task(_drain(process, errors))  # ошибки читаем всегда: иначе ffmpeg встанет
    try:
        assert process.stdout is not None
        chunks = _whole_samples(process.stdout)
        yield await _first(chunks, process, errors, timeout_s)
        async for chunk in chunks:
            yield chunk
        if await process.wait() != 0:
            _log.warning("ffmpeg оборвал файл: %s", _tail(errors))
    finally:
        await _stop(process)
        draining.cancel()


async def _first(
    chunks: AsyncIterator[bytes], process: asyncio.subprocess.Process, errors: deque[bytes], timeout_s: float
) -> bytes:
    """Первый кусок PCM; нет его — AudioUndecodable с причиной."""
    try:
        async with asyncio.timeout(timeout_s):
            return await anext(chunks)
    except TimeoutError as error:
        raise AudioUndecodable(f"{FILE_UNDECODABLE} (разбор дольше {timeout_s:g} с)") from error
    except StopAsyncIteration:
        pass
    if await process.wait() != 0:
        _log.warning("ffmpeg не разобрал файл: %s", _tail(errors))
        raise AudioUndecodable(FILE_UNDECODABLE)
    raise AudioUndecodable(FILE_SILENT)


async def _whole_samples(stdout: asyncio.StreamReader) -> AsyncGenerator[bytes]:
    """Куски PCM из stdout без разрыва отсчётов: нечётный байт ждёт пары, в конце отбрасывается."""
    tail = b""
    while data := await stdout.read(FILE_CHUNK_BYTES):
        data = tail + data
        cut = len(data) & ~1
        tail = data[cut:]
        if cut:
            yield data[:cut]


async def _drain(process: asyncio.subprocess.Process, errors: deque[bytes]) -> None:
    """Читает stderr ffmpeg до конца, помня последние ERRORS_TAIL байтов."""
    assert process.stderr is not None
    kept = 0
    while data := await process.stderr.read(4096):
        errors.append(data)
        kept += len(data)
        while kept - len(errors[0]) >= ERRORS_TAIL:
            kept -= len(errors.popleft())


def _tail(errors: deque[bytes]) -> str:
    return b"".join(errors).decode(errors="replace")[-ERRORS_TAIL:]


async def _stop(process: asyncio.subprocess.Process) -> None:
    """Останавливает ffmpeg, если он ещё работает, и ждёт его."""
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    await process.wait()


def _arguments(program: str, protocols: str, formats: str, source: str, max_s: int) -> list[str]:
    """Команда ffmpeg: звук из source, PCM в stdout, ошибки — коротко в stderr.

    protocols и formats — белые списки: никаких вложенных адресов и файлов (HLS, concat),
    только форматы договора.
    """
    return [
        program,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        protocols,
        "-format_whitelist",
        formats,
        "-i",
        source,
        "-vn",
        "-t",
        str(max_s),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "pipe:1",
    ]
