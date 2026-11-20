"""Помощники очереди объявлений: звук попытки, закрытие синтеза, вопрос в конце текста, событие."""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterator

_log = logging.getLogger("smartesp.notify.announcer")

STYLE = "normal"  # объявления звучат стилем по умолчанию
_CLOSERS = " \t\n\"'»“”)!.…"  # кавычки, скобки и «!», «.» после «?» («Правда?!», «Что?..»)


class Speech:
    """Звук одной попытки: первый кусок синтезирован до announce; помнит, если синтез упал дальше."""

    def __init__(self, first: bytes, rest: AsyncIterator[bytes]) -> None:
        """first — уже готовый первый кусок; rest — остаток потока синтеза."""
        self._first = first
        self._rest = rest
        self.failed = False

    async def stream(self) -> AsyncIterator[bytes]:
        """Весь звук: первый кусок и остаток; сбой синтеза отмечается в failed и пробрасывается."""
        try:
            yield self._first
            async for chunk in self._rest:
                yield chunk
        except Exception:
            self.failed = True
            raise
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        """Закрывает поток синтеза (колонка могла так и не взять звук: busy, обрыв)."""
        await close_audio(self._rest)


async def close_audio(audio: AsyncIterator[bytes]) -> None:
    """Закрывает поток синтеза, если это генератор."""
    if isinstance(audio, AsyncGenerator):
        await audio.aclose()


def is_question(text: str) -> bool:
    """True, если текст кончается вопросом (Кузя ждёт ответа)."""
    return text.rstrip(_CLOSERS).endswith("?")


def log_crash(task: asyncio.Task[None]) -> None:
    """Задача очереди упала (не должна) — в журнал."""
    if not task.cancelled() and task.exception() is not None:
        _log.error("Очередь объявлений %s упала", task.get_name(), exc_info=task.exception())


def event_data(number: int, text: str, source: str, status: str, device_id: str) -> dict[str, object]:
    """Данные turn_finished объявления (имя колонки — device_id; очередь подставляет настоящее)."""
    return {
        "turn_id": f"a{number}",
        "device_id": device_id,
        "device_name": device_id,
        "at": time.time(),
        "text": "",
        "annotations": [],
        "style": STYLE,
        "answer": text,
        "status": status,
        "path": [source],
        "delegations": [],
        "origin": "core",
        "kind": "announcement",
    }
