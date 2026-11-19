"""Запуск фиксированных AppleScript через `osascript`.

Текст скрипта всегда наш (константы из scripts.py) и идёт через stdin; данные
человека (поисковый запрос, громкость) — только аргументами `on run argv`,
поэтому в код скрипта они не попадают.
"""

import asyncio
from collections.abc import Sequence

from mac_media_mcp.system import PermissionDenied, Player, SystemFailure

OSASCRIPT = "/usr/bin/osascript"
TIMEOUT_S = 15.0

# Ошибки Apple Events: нет разрешения (Автоматизация) и «приложение не запущено».
_NOT_AUTHORIZED = ("-1743", "Not authorized")
_NOT_RUNNING = "-600"

_APP_TITLES: dict[Player, str] = {"Music": "«Музыка»", "Spotify": "Spotify"}


def script_error(stderr: str, app: Player | None) -> Exception:
    """Переводит stderr упавшего osascript в PermissionDenied или SystemFailure."""
    if app is None:
        return SystemFailure("Не получилось выполнить системную команду звука.")
    if any(mark in stderr for mark in _NOT_AUTHORIZED):
        return PermissionDenied(app)
    title = _APP_TITLES[app]
    if _NOT_RUNNING in stderr:
        return SystemFailure(f"Приложение {title} не запущено.")
    return SystemFailure(f"Не получилось управлять приложением {title}.")


def _timeout_error(app: Player | None) -> SystemFailure:
    if app is None:
        return SystemFailure("Системная команда звука не отвечает.")
    return SystemFailure(
        f"Приложение {_APP_TITLES[app]} не отвечает. "
        "Возможно, macOS спрашивает разрешение — посмотри на экран Mac."
    )


async def run_script(
    script: str,
    args: Sequence[str] = (),
    *,
    app: Player | None = None,
    timeout_s: float = TIMEOUT_S,
) -> str:
    """Выполняет script с аргументами args; возвращает stdout без хвостового перевода строки.

    app — каким приложением управляет скрипт (для текста ошибки); None — системная команда.
    Ошибка — PermissionDenied или SystemFailure.
    """
    process = await asyncio.create_subprocess_exec(
        OSASCRIPT,
        "-",
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(script.encode()), timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise _timeout_error(app) from None
    if process.returncode != 0:
        raise script_error(stderr.decode(errors="replace"), app)
    return stdout.decode(errors="replace").rstrip("\n")
