"""Обновления колонок по воздуху: проверка файла, одноразовая ссылка для колонки, команда update.

Звук сигнала (what "sound", meta tone) — тот же путь, без перезагрузки колонки; пустой файл —
команда без ссылки: колонка удаляет свой звук и снова играет встроенный.

Колонка сама качает файл с ядра: GET /device/files/<токен> (без токена API — у колонки его нет;
токен случайный, живёт TOKEN_TTL_S). Ход и итог колонка присылает событиями update_status (их
учитывает хаб колонок).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path

from smartesp.contracts import SOUND_TONES, UpdateRefusedError, UpdateWhat

_log = logging.getLogger(__name__)
TOKEN_TTL_S = 900.0  # 15 минут: колонке хватит, ссылка не живёт вечно
MAX_FIRMWARE = 0x300000  # половина флеша под прошивку (разметка esp_sr_16), байт
MAX_MODEL = 1024 * 1024
ESP_IMAGE_MAGIC = 0xE9  # первый байт образа прошивки ESP32
MODEL_META = ("cutoff", "window", "arena")
MAX_SOUND = 96000  # 3 с PCM 16 кГц моно s16le — предел колонки
OLD_FIRMWARE = "колонка не подключена или её прошивка старше 0.5.0 — первый раз прошейте 0.5.0 по USB"

OLD_SOUNDS = "колонка не подключена или её прошивка не умеет свои звуки — нужна 0.6.0"

type Send = Callable[[str, dict[str, object]], Awaitable[bool]]


def check_file(what: UpdateWhat, data: bytes, meta: Mapping[str, object] | None) -> None:
    """Файл подходит колонке; нет — UpdateRefusedError с понятным текстом."""
    if what == "firmware":
        if not data or data[0] != ESP_IMAGE_MAGIC:
            raise UpdateRefusedError(
                "это не файл прошивки ESP32 (.bin из «Экспорт бинарного файла» или tools/build.sh)"
            )
        if len(data) > MAX_FIRMWARE:
            raise UpdateRefusedError(f"прошивка больше {MAX_FIRMWARE // 1024} КБ — не поместится")
        return
    if what == "sound":
        if meta is None or meta.get("tone") not in SOUND_TONES:
            raise UpdateRefusedError("у звука нет сигнала (tone)")
        if len(data) > MAX_SOUND or len(data) % 2:
            raise UpdateRefusedError("звук — PCM 16 кГц моно не длиннее 3 с")
        return
    if not data or len(data) > MAX_MODEL:
        raise UpdateRefusedError("модель пустая или больше 1 МБ")
    if meta is None or any(key not in meta for key in MODEL_META):
        raise UpdateRefusedError("у модели нет порога, окна или размера арены (manifest.json)")


class Updates:
    """Обновления: файлы со ссылками в folder, команды колонкам через send(колонка, команда)."""

    def __init__(self, folder: Path, send: Send, clock: Callable[[], float] = time.monotonic) -> None:
        """folder — папка файлов (очищается при первом обновлении); send — DeviceHub.send_update."""
        self._folder = folder
        self._ready = False  # папку создаём при первом обновлении: ядро без обновлений её не трогает
        self._send = send
        self._clock = clock
        self._files: dict[str, tuple[Path, float]] = {}  # токен → (файл, когда истекает)

    async def install(
        self, device_id: str, what: UpdateWhat, data: bytes, meta: Mapping[str, object] | None = None
    ) -> None:
        """Проверяет файл, выдаёт ссылку и шлёт колонке update; см. UpdatePort.install."""
        check_file(what, data, meta)
        if what == "sound" and not data:  # убрать свой звук: качать нечего
            await self._command(device_id, {"what": what, "tone": _tone(meta), "size": 0}, None)
            return
        if not self._ready:
            shutil.rmtree(self._folder, ignore_errors=True)  # файлы прошлого запуска — уже не нужны
            self._folder.mkdir(parents=True, exist_ok=True)
            self._ready = True
        self._forget_expired()
        token = secrets.token_urlsafe(24)
        path = self._folder / f"{token}.bin"
        path.write_bytes(data)
        self._files[token] = (path, self._clock() + TOKEN_TTL_S)
        payload: dict[str, object] = {
            "what": what,
            "path": f"/device/files/{token}",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if what == "model" and meta is not None:
            payload |= {key: meta[key] for key in (*MODEL_META, "word") if key in meta}
        if what == "sound":
            payload["tone"] = _tone(meta)
        await self._command(device_id, payload, token)

    async def _command(self, device_id: str, payload: dict[str, object], token: str | None) -> None:
        """Шлёт update; колонка не приняла — ссылка отзывается, UpdateRefusedError."""
        if not await self._send(device_id, payload):
            if token is not None:
                self._drop(token)
            raise UpdateRefusedError(OLD_SOUNDS if payload["what"] == "sound" else OLD_FIRMWARE)
        _log.info("Обновление %s → %s: %s байт", payload["what"], device_id, payload["size"])

    def file(self, token: str) -> Path | None:
        """Файл по токену; нет или срок вышел — None."""
        self._forget_expired()
        entry = self._files.get(token)
        return entry[0] if entry is not None and entry[0].exists() else None

    def _forget_expired(self) -> None:
        now = self._clock()
        for token in [t for t, (_, until) in self._files.items() if until <= now]:
            self._drop(token)

    def _drop(self, token: str) -> None:
        path, _ = self._files.pop(token, (None, 0.0))
        if path is not None:
            path.unlink(missing_ok=True)


def _tone(meta: Mapping[str, object] | None) -> str:
    """Сигнал звука из meta (уже проверен check_file)."""
    return str(meta["tone"]) if meta is not None else ""
