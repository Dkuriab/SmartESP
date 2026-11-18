"""История диалога, общая на дом."""

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from smartesp.contracts import ChatMessage


@dataclass(frozen=True)
class _Exchange:
    """Один завершённый ход: вопрос, ответ и когда он записан."""

    at: float
    user: str
    assistant: str


class History:
    """Последние ходы диалога; слишком старые забываются."""

    def __init__(self, max_turns: int, max_age_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        """max_turns — сколько последних ходов помнить; max_age_s — через сколько секунд ход забывается.

        clock — источник времени (для тестов).
        """
        self._max_age_s = max_age_s
        self._clock = clock
        self._exchanges: deque[_Exchange] = deque(maxlen=max_turns)

    def messages(self) -> list[ChatMessage]:
        """Возвращает живые ходы как пары сообщений user/assistant, от старых к новым."""
        oldest = self._clock() - self._max_age_s
        while self._exchanges and self._exchanges[0].at < oldest:
            self._exchanges.popleft()
        result: list[ChatMessage] = []
        for exchange in self._exchanges:
            result.append(ChatMessage("user", exchange.user))
            result.append(ChatMessage("assistant", exchange.assistant))
        return result

    def add(self, user: str, assistant: str) -> None:
        """Запоминает завершённый ход: текст вопроса и полный текст ответа."""
        self._exchanges.append(_Exchange(self._clock(), user, assistant))
