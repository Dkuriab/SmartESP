"""Бюджет времени инструмента и перевод системных ошибок в ответы для человека.

Хаб ядра ждёт инструмент 15 с. Инструмент укладывается в свой бюджет (10 с):
каждый следующий системный вызов получает только остаток, а когда бюджет
кончился — вызов не делается, человек слышит честный ответ, кто не отвечает.
"""

import asyncio
from collections.abc import Awaitable, Callable

from mac_media_mcp.system import PermissionDenied, PermissionTarget, Player, SystemFailure, SystemTimeout

BUDGET_S = 10.0

AUTOMATION_HINT = "Разреши в Настройках → Конфиденциальность → Автоматизация."
ACCESSIBILITY_HINT = "Разреши в Настройках → Конфиденциальность → Универсальный доступ."
WAITING_HINT = "Возможно, macOS ждёт разрешения — проверь окно запроса."

# Как назвать приложение в ответе («управлять приложением …»).
_APP_NAMES: dict[Player, str] = {"Music": "«Музыка»", "Spotify": "Spotify"}


class MediaError(Exception):
    """Ошибка для человека: текст готов к озвучке; permission — это отказ macOS в разрешении."""

    def __init__(self, text: str, *, permission: bool = False) -> None:
        super().__init__(text)
        self.permission = permission


def permission_text(target: PermissionTarget) -> str:
    """Честный ответ об отказе macOS и где дать разрешение."""
    if target == "keys":
        return f"Нет разрешения нажимать медиа-клавиши. {ACCESSIBILITY_HINT}"
    return f"Нет разрешения управлять приложением {_APP_NAMES[target]}. {AUTOMATION_HINT}"


def silent_text(app: Player | None) -> str:
    """Ответ, когда плеер (или сама система, app=None) не ответил вовремя."""
    if app is None:
        return "Mac не отвечает на команду звука."
    return f"Приложение {_APP_NAMES[app]} не отвечает. {WAITING_HINT}"


class Budget:
    """Время на один вызов инструмента; создаётся в начале инструмента."""

    def __init__(self, seconds: float) -> None:
        self._deadline = asyncio.get_running_loop().time() + seconds

    def remaining(self) -> float:
        """Сколько секунд осталось (может быть ≤ 0)."""
        return self._deadline - asyncio.get_running_loop().time()

    async def run[T](self, call: Callable[[], Awaitable[T]], app: Player | None = None) -> T:
        """Делает системный вызов call не дольше остатка бюджета.

        app — какой плеер отвечает (для текста). Бюджет кончился — вызов не делается.
        Отказ macOS, сбой и молчание — MediaError с понятным текстом.
        """
        left = self.remaining()
        if left <= 0:
            raise MediaError(silent_text(app))
        try:
            async with asyncio.timeout(left):
                return await call()
        except TimeoutError:
            raise MediaError(silent_text(app)) from None
        except PermissionDenied as error:
            raise MediaError(permission_text(error.target), permission=True) from None
        except SystemTimeout as error:
            raise MediaError(silent_text(error.app)) from None
        except SystemFailure as error:
            raise MediaError(str(error)) from None
