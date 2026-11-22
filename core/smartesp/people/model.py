"""Модель отпечатков голоса: какая, где лежит и скачивание с проверкой sha256.

3D-Speaker CAM++ (zh-en, ~200 тыс. голосов, Apache-2.0) в ONNX из релиза sherpa-onnx;
выбор и замеры — docs/superpowers/specs/2026-11-22-people-design.md. Версия закреплена
адресом релиза и хешем файла: другой файл по тому же адресу не примется.
"""

import hashlib
import logging
from collections.abc import Callable
from pathlib import Path

import httpx

MODEL_ID = "campplus-zh-en-advanced"
MODEL_TITLE = "3D-Speaker CAM++ (zh-en)"
MODEL_FILE = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
MODEL_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/" + MODEL_FILE
MODEL_SHA256 = "53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b"
MODEL_SIZE_MB = 28
TIMEOUT = httpx.Timeout(60.0, connect=30.0)  # на каждый кусок: зависший поток обрывается

Progress = Callable[[int, int | None], None]  # (скачано байт, всего или None)

_log = logging.getLogger(__name__)


class ModelDownloadError(Exception):
    """Модель не скачалась: сеть, ответ сервера или не тот файл."""


def model_path(home: Path) -> Path:
    """Файл модели в папке данных: <home>/models/speaker/<файл>."""
    return home / "models" / "speaker" / MODEL_FILE


def _fetch(client: httpx.Client, part: Path, progress: Progress | None) -> str:
    """Качает MODEL_URL в part; возвращает sha256 скачанного."""
    digest = hashlib.sha256()
    with client.stream("GET", MODEL_URL, follow_redirects=True, timeout=TIMEOUT) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0)) or None
        done = 0
        with part.open("wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
    return digest.hexdigest()


def download_model(
    home: Path, *, client: httpx.Client | None = None, progress: Progress | None = None
) -> Path:
    """Скачивает модель в <home>/models/speaker (синхронно, вызывать из потока).

    Через <файл>.part и проверку sha256; при сбое — ModelDownloadError, недокачанного не остаётся.
    """
    target = model_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    own = client is None
    http = client or httpx.Client()
    try:
        digest = _fetch(http, part, progress)
        if digest != MODEL_SHA256:
            raise ModelDownloadError(f"Скачан не тот файл модели (sha256 {digest[:12]}…)")
        part.replace(target)
    except (httpx.HTTPError, OSError) as error:
        raise ModelDownloadError(f"Не удалось скачать модель узнавания: {error}") from error
    finally:
        part.unlink(missing_ok=True)
        if own:
            http.close()
    _log.info("Модель узнавания голоса скачана: %s", target)
    return target
