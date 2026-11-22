"""Приветствие колонки (hello): версия, протокол, возможности, свои звуки, частоты потоков."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_RATE = 192000


@dataclass(frozen=True)
class Hello:
    """Приветствие колонки. Прошивка v1 не шлёт device_id: тогда None и protocol=1.

    caps — возможности сверх протокола («sounds» — свои звуки, прошивка 0.6.0; «echo» — калибровка
    эха, 0.7.0); sounds — SHA-256 своих звуков по сигналу (нет сигнала — встроенный); stream_rates —
    частоты потоков, которые колонка играет (нет поля — пусто: только 16 кГц). Неверные элементы
    пропускаются.
    """

    device_id: str | None
    fw: str
    protocol: int
    caps: frozenset[str] = frozenset()
    sounds: dict[str, str] = field(default_factory=dict[str, str])
    stream_rates: tuple[int, ...] = ()


def parse_hello(data: dict[str, Any]) -> Hello | None:
    """hello из JSON; без fw, с неверным device_id или protocol — None."""
    fw = data.get("fw")
    if not isinstance(fw, str):
        return None
    device_id = data.get("device_id")
    if device_id is not None and not isinstance(device_id, str):
        return None
    protocol = data.get("protocol", 1)
    if isinstance(protocol, bool) or not isinstance(protocol, int):
        return None
    caps, sounds, rates = (
        _caps(data.get("caps")),
        _sounds(data.get("sounds")),
        _rates(data.get("stream_rates")),
    )
    return Hello(device_id, fw, protocol, caps, sounds, rates)


def _caps(value: Any) -> frozenset[str]:
    """Возможности из hello: только строки; не список — пусто."""
    items: list[Any] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
    return frozenset(item for item in items if isinstance(item, str))


def _sounds(value: Any) -> dict[str, str]:
    """Хэши звуков из hello: сигнал → SHA-256 (64 строчных шестнадцатеричных); прочее пропускается."""
    items: dict[Any, Any] = value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]
    return {
        k: v for k, v in items.items() if isinstance(k, str) and isinstance(v, str) and SHA256.fullmatch(v)
    }


def _rates(value: Any) -> tuple[int, ...]:
    """Частоты потоков из hello: целые 1..MAX_RATE по возрастанию без повторов; прочее пропускается."""
    items: list[Any] = value if isinstance(value, list) else []  # pyright: ignore[reportUnknownVariableType]
    good = {i for i in items if isinstance(i, int) and not isinstance(i, bool) and 0 < i <= MAX_RATE}
    return tuple(sorted(good))
