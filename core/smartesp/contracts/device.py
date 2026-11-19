"""Договор: то, что разговору нужно от колонок."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from .audio import Utterance

# Итог объявления: доиграно; перебито словом или отменено (считаем услышанным);
# колонка занята; обрыв связи или нет playback_done за срок воспроизведения + 15 с.
Delivery = Literal["delivered", "interrupted", "busy", "lost"]


@dataclass(frozen=True)
class DeviceInfo:
    """Сведения о колонке для интерфейса; remote, fw и last_seen — по последней сессии."""

    device_id: str
    name: str
    connected: bool
    remote: str
    fw: str
    last_seen: float | None  # time.time() последнего кадра; None — колонка не подключалась
    protocol: int = 0  # версия протокола последней сессии; 0 — колонка не подключалась


class DevicePort(Protocol):
    """Порт к колонкам; реализует DeviceHub."""

    async def next_utterance(self) -> Utterance:
        """Ждёт следующую реплику от любой колонки."""
        ...

    def is_active(self, device_id: str, turn: int) -> bool:
        """Возвращает True, если ход turn колонки device_id ещё актуален."""
        ...

    async def play(self, device_id: str, turn: int, audio: AsyncIterator[bytes]) -> None:
        """Проигрывает поток PCM на колонке в рамках хода turn."""
        ...

    async def send_tone(self, device_id: str, name: str) -> None:
        """Просит колонку сыграть короткий сигнал по имени."""
        ...

    def device_name(self, device_id: str) -> str:
        """Возвращает человеческое имя колонки."""
        ...

    def supports_proactive(self, device_id: str) -> bool:
        """True, если колонка подключена и умеет речь по инициативе ядра (протокол ≥ 3)."""
        ...

    async def announce(self, device_id: str, audio: AsyncIterator[bytes]) -> Delivery:
        """Говорит на колонке новым ходом ядра (колонка, приняв его, сама играет сигнал «внимание»,
        затем звук) и ждёт итог доставки."""
        ...

    async def listen(self, device_id: str) -> bool:
        """Включает колонке микрофон ходом ядра; реплика придёт в next_utterance с origin "listen".

        Возвращает True, если команда ушла; False — колонка не подключена, протокол < 3 или занята.
        """
        ...

    async def listen_after(self, device_id: str, turn: int) -> None:
        """Ждёт, пока колонка доиграет ответ хода turn, и включает ей микрофон (listen).

        Ход закончился иначе (перебили, отменили, обрыв) или ожидание затянулось — ничего не делает.
        """
        ...

    def last_active_device(self) -> str | None:
        """Колонка последнего принятого хода (по слову или прослушиванию), если она подключена."""
        ...
