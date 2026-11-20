"""Предел частоты запросов в интернет: не больше N за окно, плюс пауза после блокировки."""

import time
from collections import deque
from collections.abc import Callable


class RateLimiter:
    """Скользящее окно: allow() пропускает не больше limit вызовов за window секунд.

    Отказанные вызовы не считаются. pause() — не ходить в сеть до конца паузы
    (например, поиск ответил капчей). Время — clock (для тестов подделка).
    """

    def __init__(self, limit: int, window: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._calls: deque[float] = deque()
        self._paused_until = 0.0

    def allow(self) -> bool:
        """True — можно идти в сеть (вызов засчитан); False — предел исчерпан."""
        now = self._clock()
        while self._calls and now - self._calls[0] >= self._window:
            self._calls.popleft()
        if len(self._calls) >= self._limit:
            return False
        self._calls.append(now)
        return True

    def pause(self, seconds: float) -> None:
        """Не ходить в сеть seconds секунд."""
        self._paused_until = self._clock() + seconds

    def paused(self) -> bool:
        """True — пауза ещё идёт."""
        return self._clock() < self._paused_until
