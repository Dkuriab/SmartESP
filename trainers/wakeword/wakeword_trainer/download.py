"""Скачивание данных для обучения (один раз: качает ~7 ГБ, на диске ~25 ГБ): признаки и фоны.

- Отрицательные примеры — признаки, посчитанные авторами microWakeWord (kahrendt/microwakeword,
  CC-BY-NC-4.0 — только для личного некоммерческого использования): речь, тишина, застолье и
  отдельное застолье для замера «ложных в час».
- Фоны для аугментации: эхо комнат (MIT RIR), музыка (FMA xs), звуки (часть AudioSet).
Повторный запуск докачивает недостающее; готовое помечается файлом .done.
"""

from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path

import httpx
import numpy as np
import soundfile

from . import progress
from .audio import resample, to_int16, write_wav

HF = "https://huggingface.co/datasets"
NEGATIVES = ("speech", "dinner_party", "no_speech", "dinner_party_eval")
RIR_TREE = (
    "https://huggingface.co/api/datasets/davidscripka/MIT_environmental_impulse_responses/tree/main/16khz"
)
RIR_FILE = f"{HF}/davidscripka/MIT_environmental_impulse_responses/resolve/main/"
FMA = f"{HF}/mchl914/fma_xsmall/resolve/main/fma_xs.zip"
AUDIOSET = f"{HF}/agkphysics/AudioSet/resolve/5a2fa42a15/data/bal_train09.tar"  # .tar до перехода на Parquet
CHUNK = 1 << 20


def fetch(client: httpx.Client, url: str, dest: Path, stage: str) -> Path:
    """Качает url в dest (докачка .part по Range); уже скачанный файл не трогает."""
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code == 416:  # уже всё скачано
            part.rename(dest)
            return dest
        response.raise_for_status()
        if have and response.status_code != 206:
            have = 0  # сервер не умеет докачку — заново
        total = have + int(response.headers.get("content-length", 0))
        with part.open("ab" if have else "wb") as out:
            for chunk in response.iter_bytes(CHUNK):
                out.write(chunk)
                have += len(chunk)
                progress.step(stage, have >> 20, total >> 20)
    part.rename(dest)
    return dest


def _done(folder: Path) -> bool:
    return (folder / ".done").exists()


def _mark(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".done").touch()


def negatives(client: httpx.Client, cache: Path) -> None:
    """Готовые отрицательные признаки: cache/negatives/<имя>/…/*_mmap."""
    for name in NEGATIVES:
        folder = cache / "negatives" / name
        if _done(folder):
            continue
        archive = fetch(
            client,
            f"{HF}/kahrendt/microwakeword/resolve/main/{name}.zip",
            cache / f"{name}.zip",
            f"скачиваю {name}",
        )
        progress.log(f"Распаковываю {name}…")
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(cache / "negatives")
        archive.unlink()
        _mark(folder)


def rirs(client: httpx.Client, cache: Path) -> None:
    """Эхо комнат MIT (16 кГц, 270 файлов): cache/backgrounds/mit_rirs."""
    folder = cache / "backgrounds" / "mit_rirs"
    if _done(folder):
        return
    files = [
        item["path"]
        for item in client.get(RIR_TREE).raise_for_status().json()
        if item["path"].endswith(".wav")
    ]
    for i, name in enumerate(files, 1):
        fetch(client, RIR_FILE + name, folder / Path(name).name, "скачиваю эхо комнат")
        progress.step("эхо комнат", i, len(files))
    _mark(folder)


def _convert_all(sources: list[Path], folder: Path, stage: str) -> None:
    """Аудиофайлы (mp3, flac, …) → WAV 16 кГц моно; нечитаемые пропускаются."""
    for i, src in enumerate(sources, 1):
        try:
            data, rate = soundfile.read(str(src), dtype="float32", always_2d=True)
        except (soundfile.LibsndfileError, RuntimeError):
            continue
        write_wav(folder / f"{src.stem}.wav", to_int16(resample(np.asarray(data.mean(axis=1)), rate)))
        progress.step(stage, i, len(sources))


def background_audio(client: httpx.Client, cache: Path) -> None:
    """Музыка FMA и звуки AudioSet → cache/backgrounds/{fma_16k,audioset_16k}."""
    for name, url, kind in (("fma_16k", FMA, "zip"), ("audioset_16k", AUDIOSET, "tar")):
        folder = cache / "backgrounds" / name
        if _done(folder):
            continue
        archive = fetch(client, url, cache / Path(url).name, f"скачиваю {name}")
        raw = cache / f"{name}_raw"
        progress.log(f"Распаковываю {name}…")
        if kind == "zip":
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(raw)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(raw, filter="data")
        sources = sorted(p for p in raw.rglob("*") if p.suffix.lower() in (".mp3", ".flac", ".wav", ".ogg"))
        _convert_all(sources, folder, f"перевожу {name} в 16 кГц")
        shutil.rmtree(raw)
        archive.unlink()
        _mark(folder)


def download_all(cache: Path) -> None:
    """Всё нужное для обучения; повторный запуск докачивает недостающее."""
    timeout = httpx.Timeout(30.0, read=120.0)
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        rirs(client, cache)
        background_audio(client, cache)
        negatives(client, cache)
    progress.log("Данные для обучения скачаны.")
