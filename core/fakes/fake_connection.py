"""Подделка соединения колонки: тест кладёт входящие кадры и читает исходящие."""

from __future__ import annotations

import asyncio
import json
from typing import Any

_CLOSED = object()  # метка «соединение закрыто» в очереди входящих


class FakeConnection:
    def __init__(self, remote: str = "10.0.0.7:5000") -> None:
        self.remote = remote
        self.sent: list[str | bytes] = []
        self.closed = False
        self._incoming: asyncio.Queue[object] = asyncio.Queue()
        self._sends_open = asyncio.Event()  # сброшено — отправки висят (Wi-Fi пропал)
        self._sends_open.set()

    def feed(self, frame: str | bytes) -> None:
        """Кладёт входящий кадр (текст или звук)."""
        self._incoming.put_nowait(frame)

    def feed_json(self, kind: str, **fields: Any) -> None:
        """Кладёт текстовое сообщение протокола {"type": kind, ...}."""
        self.feed(json.dumps({"type": kind, **fields}))

    def fail(self) -> None:
        """Обрыв связи: дальше receive и отправка кидают ConnectionError."""
        self.closed = True
        self._incoming.put_nowait(_CLOSED)

    def stall(self) -> None:
        """Полуоткрытая связь: отправки висят, пока не вызван release()."""
        self._sends_open.clear()

    def release(self) -> None:
        """Отправки снова проходят."""
        self._sends_open.set()

    def sent_json(self) -> list[dict[str, Any]]:
        """Отправленные текстовые сообщения, разобранные из JSON."""
        # громкость хаб шлёт сам при подключении — в проверках ходов она не нужна
        frames = [json.loads(m) for m in self.sent if isinstance(m, str)]
        return [f for f in frames if f.get("type") != "volume"]

    def sent_audio(self) -> bytes:
        """Весь отправленный звук подряд."""
        return b"".join(m for m in self.sent if isinstance(m, bytes))

    async def receive(self) -> str | bytes:
        if self.closed:
            raise ConnectionError("closed")
        frame = await self._incoming.get()
        if frame is _CLOSED:
            raise ConnectionError("closed")
        assert isinstance(frame, str | bytes)
        return frame

    async def send_text(self, text: str) -> None:
        await self._sends_open.wait()
        self._check_open()
        self.sent.append(text)

    async def send_bytes(self, data: bytes) -> None:
        await self._sends_open.wait()
        self._check_open()
        self.sent.append(data)

    async def close(self) -> None:
        self.fail()

    def _check_open(self) -> None:
        if self.closed:
            raise ConnectionError("closed")
