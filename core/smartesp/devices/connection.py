"""Соединение с колонкой: то, что хабу нужно от WebSocket."""

from __future__ import annotations

from typing import Protocol


class DeviceConnection(Protocol):
    """Адаптер над WebSocket одной колонки. После закрытия все вызовы кидают ConnectionError."""

    @property
    def remote(self) -> str:
        """Адрес колонки (для журнала и id прошивки v1)."""
        ...

    async def receive(self) -> str | bytes:
        """Ждёт следующий кадр: текст (JSON) или звук. ConnectionError — соединение закрыто."""
        ...

    async def send_text(self, text: str) -> None:
        """Шлёт текстовый кадр. ConnectionError — соединение закрыто."""
        ...

    async def send_bytes(self, data: bytes) -> None:
        """Шлёт звуковой кадр. ConnectionError — соединение закрыто."""
        ...

    async def close(self) -> None:
        """Закрывает соединение; ждущий receive получает ConnectionError."""
        ...


async def close_quietly(conn: DeviceConnection) -> None:
    """Закрывает соединение; уже оборванное — не ошибка."""
    try:
        await conn.close()
    except ConnectionError:
        pass
