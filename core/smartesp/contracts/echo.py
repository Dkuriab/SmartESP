"""Договор: сдвиг образца эхоподавления колонки и его калибровка (прошивка 0.7.0, возможность «echo»)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ECHO_CAP = "echo"  # в caps hello: колонка умеет echo_calibrate / echo_delay и шлёт echo_status
MAX_ECHO_DELAY_MS = 300

# Сдвиг сейчас (при подключении и после ручной правки); калибровку попросили; идёт; готово; не вышло.
EchoState = Literal["current", "sent", "running", "done", "failed"]


@dataclass(frozen=True)
class EchoCalibration:
    """Сдвиг образца колонки: delay_ms — сейчас, previous_ms — до калибровки; confidence — уверенность
    0..1; error — busy | quiet (динамик не играл) | weak (микрофон не услышал уверенно) | ""."""

    state: EchoState
    delay_ms: int
    previous_ms: int
    confidence: float
    error: str
    at: float  # time.time() последнего изменения


class EchoRefusedError(Exception):
    """Калибровка или правка не отправлена: колонки нет, не в сети, старая прошивка, занята."""


class EchoPort(Protocol):
    """Калибровка эха для API; реализует DeviceHub."""

    async def calibrate_echo(self, device_id: str) -> None:
        """Просит свободную колонку откалибровать сдвиг образца; итог — DeviceInfo.echo и события
        device_echo. Отказ — EchoRefusedError с понятным текстом."""
        ...

    async def set_echo_delay(self, device_id: str, delay_ms: int) -> None:
        """Задаёт колонке сдвиг образца вручную (0..300 мс). Отказ — EchoRefusedError."""
        ...
