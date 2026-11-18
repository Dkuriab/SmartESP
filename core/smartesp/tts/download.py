"""Скачивание голосов: атомарно, без недокачанных файлов, и выбор голоса при старте."""

import logging
import shutil
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx

from .catalog import (
    PIPER_NAME,
    SILERO_FILE,
    VOSK_DIR,
    catalog,
    is_downloaded,
    voice_path,
)

log = logging.getLogger(__name__)

PIPER_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/{lang}/{locale}/{name}/{quality}/{voice}"
)
SILERO_URL = "https://models.silero.ai/models/tts/ru/" + SILERO_FILE
VOSK_URL = "https://alphacephei.com/vosk/models/" + VOSK_DIR + ".zip"
TIMEOUT = httpx.Timeout(60.0, connect=30.0)  # 60 с — на каждый кусок, зависший поток обрывается
Progress = Callable[[int, int | None], None]


class VoiceDownloadError(Exception):
    """Голос не скачался: сеть, ответ сервера или битый архив."""


class VoiceUnavailableError(Exception):
    """Нет ни нужного голоса, ни скачанного запасного."""


def _fetch(client: httpx.Client, url: str, dest: Path, progress: Progress | None) -> None:
    """Качает url в <dest>.part и переименовывает в dest; при сбое .part удаляется."""
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with client.stream("GET", url, follow_redirects=True, timeout=TIMEOUT) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0)) or None
            done, step = 0, 0
            with part.open("wb") as out:
                for chunk in response.iter_bytes():
                    out.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
                    if total and done * 10 // total > step:
                        step = done * 10 // total
                        log.info("Скачивание %s: %d%%", dest.name, step * 10)
        part.replace(dest)
    except (httpx.HTTPError, OSError) as exc:
        raise VoiceDownloadError(f"Не удалось скачать {url}: {exc}") from exc
    finally:
        part.unlink(missing_ok=True)


def _unpack(archive: Path, target: Path) -> None:
    """Распаковывает zip во временную папку рядом и переименовывает VOSK_DIR на место."""
    tmp = target.parent / f".unpack-{uuid.uuid4().hex}"
    try:
        with zipfile.ZipFile(archive) as z:
            root = tmp.resolve()
            for member in z.namelist():
                if not (root / member).resolve().is_relative_to(root):
                    raise VoiceDownloadError(f"Архив небезопасен: {member}")
            z.extractall(tmp)
        inner = tmp / target.name
        if not inner.is_dir():
            raise VoiceDownloadError(f"В архиве нет папки {target.name}")
        inner.replace(target)
    except (zipfile.BadZipFile, OSError) as exc:
        raise VoiceDownloadError(f"Архив повреждён: {exc}") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _piper_urls(voice: str) -> list[str]:
    locale, name, quality = voice.split("-", 2)
    base = PIPER_URL.format(lang=locale.split("_")[0], locale=locale, name=name, quality=quality, voice=voice)
    return [base + ".onnx", base + ".onnx.json"]


def _download(kind: str, voice: str, home: Path, client: httpx.Client, progress: Progress | None) -> None:
    target = voice_path(kind, voice, home)
    if kind == "piper":
        # сначала .json, затем .onnx: голос считается скачанным по .onnx
        onnx_url, json_url = _piper_urls(voice)
        _fetch(client, json_url, target.with_name(target.name + ".json"), progress)
        _fetch(client, onnx_url, target, progress)
    elif kind == "silero":
        _fetch(client, SILERO_URL, target, progress)
    else:
        archive = target.parent / (VOSK_DIR + ".zip")
        try:
            _fetch(client, VOSK_URL, archive, progress)
            _unpack(archive, target)
        finally:
            archive.unlink(missing_ok=True)


def download_voice(
    kind: str,
    voice: str,
    home: Path,
    *,
    client: httpx.Client | None = None,
    progress: Progress | None = None,
) -> None:
    """Скачивает голос в <home>/voices (синхронно, вызывать из потока).

    progress(скачано_байт, всего_или_None) вызывается на каждый кусок текущего файла.
    При сбое бросает VoiceDownloadError и не оставляет частичных файлов и папок.
    """
    voice_path(kind, voice, home)  # проверка имени до сети
    if kind == "piper" and not PIPER_NAME.match(voice):
        raise ValueError(f"Неизвестный голос Piper {voice!r}: URL не построить")
    own = client is None
    http = client or httpx.Client()
    try:
        _download(kind, voice, home, http, progress)
    finally:
        if own:
            http.close()


def ensure_voice(
    kind: str,
    voice: str,
    home: Path,
    *,
    download: Callable[[str, str, Path], None] = download_voice,
) -> tuple[str, str]:
    """Гарантирует голос при старте; возвращает (вид, голос), которым можно говорить.

    Нет голоса — скачивает; не вышло — берёт первый скачанный из каталога (с
    предупреждением). Нет и его — VoiceUnavailableError. Неизвестный голос — ValueError.
    """
    if is_downloaded(kind, voice, home):
        return kind, voice
    try:
        download(kind, voice, home)
        if is_downloaded(kind, voice, home):
            return kind, voice
    except VoiceDownloadError as exc:
        log.warning("Не удалось скачать голос %s/%s: %s", kind, voice, exc)
    for info in catalog(home):
        if info.downloaded:
            log.warning("Использую запасной голос %s/%s", info.kind, info.voice)
            return info.kind, info.voice
    raise VoiceUnavailableError(
        f"Голос {kind}/{voice} не скачан, запасного нет. Проверьте интернет и запустите снова."
    )
