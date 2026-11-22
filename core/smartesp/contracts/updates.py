"""Договор: обновление колонок по воздуху — прошивка и модель слова (файл качает сама колонка)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol

UpdateWhat = Literal["firmware", "model"]


class UpdateRefusedError(Exception):
    """Обновление не отправлено: колонка не подключена, прошивка старше 0.5.0 или файл не тот."""


class UpdatePort(Protocol):
    """Обновления для API и обучения."""

    async def install(
        self, device_id: str, what: UpdateWhat, data: bytes, meta: Mapping[str, object] | None = None
    ) -> None:
        """Отдаёт колонке команду update со ссылкой на data (одноразовую, на 15 минут).

        meta — для модели: cutoff, window, arena, word. Отказ — UpdateRefusedError с понятным текстом.
        Ход и итог — в DeviceInfo.update (status) и событиях device_update.
        """
        ...

    def file(self, token: str) -> Path | None:
        """Файл обновления по токену из ссылки; нет или срок вышел — None."""
        ...
