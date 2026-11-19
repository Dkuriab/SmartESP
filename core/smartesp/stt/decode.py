"""Разбор звука для распознавания: OGG/Opus, WAV и др. → PCM s16le 16 кГц моно через ffmpeg.

ffmpeg ищется в PATH, затем в обычных местах Homebrew: приложение запускает ядро с
коротким PATH, где /opt/homebrew/bin может не быть.
"""

import asyncio
import contextlib
import logging
import os
import shutil
from collections.abc import Sequence

from smartesp.contracts import SAMPLE_RATE, AskUnavailable, AudioUndecodable

_log = logging.getLogger(__name__)

FFMPEG_PLACES = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
DECODE_TIMEOUT_S = 10.0  # дольше разбор не ждём (обычно — доли секунды)
MAX_DURATION_S = 120  # длиннее — обрезаем: распознавание держит модель, а ход — не дольше 55 с
NO_FFMPEG = "Для голосовых сообщений нужен ffmpeg (brew install ffmpeg)"
UNDECODABLE = "Не получилось разобрать звук: нужен OGG/Opus или WAV"


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
            *_arguments(program),
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


def _arguments(program: str) -> list[str]:
    """Команда ffmpeg: звук из stdin, PCM в stdout, ошибки — коротко в stderr."""
    return [
        program,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",  # только stdin: никаких вложенных адресов и файлов (HLS, concat)
        "pipe",
        "-format_whitelist",  # только форматы договора
        "ogg,wav",
        "-i",
        "pipe:0",
        "-vn",
        "-t",
        str(MAX_DURATION_S),
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
