"""Логика инструментов: проверка параметров и короткие русские ответы для озвучки.

С ОС работает только через MediaSystem; ошибки для человека — MediaError.
"""

from collections.abc import Awaitable

from mac_media_mcp.system import (
    MediaKey,
    MediaSystem,
    PermissionDenied,
    PermissionTarget,
    SystemFailure,
    Track,
)

NOTHING_PLAYING = "Не вижу, что сейчас играет."
AUTOMATION_HINT = "Разреши в Настройках → Конфиденциальность → Автоматизация."
ACCESSIBILITY_HINT = "Разреши в Настройках → Конфиденциальность → Универсальный доступ."
NOT_ADJUSTABLE = "У этого устройства вывода громкость не регулируется."

# Как назвать приложение в ответе («управлять приложением …»).
_APP_NAMES: dict[PermissionTarget, str] = {"Music": "«Музыка»", "Spotify": "Spotify", "keys": ""}

_KEY_ANSWERS: dict[MediaKey, str] = {
    "play_pause": "Переключила воспроизведение.",
    "next": "Следующий трек.",
    "previous": "Предыдущий трек.",
}


class MediaError(Exception):
    """Ошибка для человека: текст готов к озвучке."""


def permission_text(target: PermissionTarget) -> str:
    """Честный ответ об отказе macOS и где дать разрешение."""
    if target == "keys":
        return f"Нет разрешения нажимать медиа-клавиши. {ACCESSIBILITY_HINT}"
    return f"Нет разрешения управлять приложением {_APP_NAMES[target]}. {AUTOMATION_HINT}"


def percent_text(value: int) -> str:
    """«40 процентов», «21 процент», «3 процента»."""
    tens, units = value % 100, value % 10
    if 11 <= tens <= 14:
        word = "процентов"
    elif units == 1:
        word = "процент"
    elif 2 <= units <= 4:
        word = "процента"
    else:
        word = "процентов"
    return f"{value} {word}"


def track_text(track: Track) -> str:
    """«Кино — «Группа крови»» или просто «Группа крови» без исполнителя."""
    title = f"«{track.name}»"
    return f"{track.artist} — {title}" if track.artist else title


def _key(text: str) -> str:
    """Имя для сравнения: без регистра, «ё» как «е», лишние пробелы убраны."""
    return " ".join(text.casefold().replace("ё", "е").split())


def match_device(devices: list[str], name: str) -> list[str]:
    """Подходящие устройства: точное совпадение без регистра, иначе все с name внутри."""
    wanted = _key(name)
    exact = [device for device in devices if _key(device) == wanted]
    if exact:
        return exact[:1]
    return [device for device in devices if wanted and wanted in _key(device)]


class MediaService:
    """Инструменты коннектора над системой Mac."""

    def __init__(self, system: MediaSystem) -> None:
        self._system = system

    async def press(self, key: MediaKey) -> str:
        """Нажимает медиа-клавишу и говорит, что сделано."""
        await _guard(self._system.press_media_key(key))
        return _KEY_ANSWERS[key]

    async def now_playing(self) -> str:
        """Что играет в запущенных плеерах; играющий важнее стоящего на паузе."""
        found: list[Track] = []
        denied: PermissionTarget | None = None
        for player in await self._system.running_players():
            try:
                track = await self._system.now_playing(player)
            except PermissionDenied as error:
                denied = error.target
                continue
            except SystemFailure:
                continue
            if track is not None:
                found.append(track)
        found.sort(key=lambda track: not track.playing)
        if found:
            prefix = "Сейчас играет" if found[0].playing else "На паузе"
            return f"{prefix}: {track_text(found[0])}."
        if denied is not None:
            raise MediaError(permission_text(denied))
        return NOTHING_PLAYING

    async def volume_get(self) -> str:
        """Текущая громкость выхода."""
        return f"Громкость {percent_text(await self._current_volume())}."

    async def volume_set(self, percent: int) -> str:
        """Ставит громкость: только целое от 0 до 100."""
        if not 0 <= percent <= 100:
            raise MediaError("Громкость — от 0 до 100 процентов.")
        await _guard(self._system.set_volume(percent))
        return f"Громкость {percent_text(percent)}."

    async def volume_change(self, delta: int) -> str:
        """Громче или тише на delta процентов; за пределы 0–100 не выходит."""
        if not -100 <= delta <= 100:
            raise MediaError("Изменение громкости — от -100 до 100 процентов.")
        current = await self._current_volume()
        target = max(0, min(100, current + delta))
        if target == current and delta > 0:
            return "Громкость уже на максимуме."
        if target == current and delta < 0:
            return "Звук уже выключен."
        await _guard(self._system.set_volume(target))
        return f"Громкость {percent_text(target)}."

    async def output_devices(self) -> str:
        """Список устройств вывода, текущее помечено «(сейчас)»."""
        devices = await _guard(self._system.output_devices())
        if not devices:
            return "Не вижу устройств вывода звука."
        current = await _guard(self._system.default_output())
        names = [f"{device} (сейчас)" if device == current else device for device in devices]
        return f"Устройства вывода: {', '.join(names)}."

    async def output_set(self, name: str) -> str:
        """Переключает вывод на устройство по имени или его части."""
        devices = await _guard(self._system.output_devices())
        matches = match_device(devices, name)
        if not matches:
            listed = ", ".join(devices) if devices else "ничего"
            raise MediaError(f"Не нашла устройство «{name.strip()}». Есть: {listed}.")
        if len(matches) > 1:
            return f"Уточни: {', '.join(matches[:-1])} или {matches[-1]}?"
        device = matches[0]
        if device == await _guard(self._system.default_output()):
            return f"Звук и так идёт через {device}."
        await _guard(self._system.set_default_output(device))
        return f"Звук теперь через {device}."

    async def music_play(self, query: str) -> str:
        """Ищет в медиатеке Music и включает; не нашлось — Spotify, если он есть."""
        query = query.strip()
        if not query:
            raise MediaError("Скажи, что включить.")
        track = await _guard(self._system.music_search_play(query))
        if track is not None:
            return f"Включаю: {track_text(track)}."
        if not await self._system.spotify_installed():
            return f"В медиатеке не нашла «{query}»."
        await _guard(self._system.spotify_search_play(query))
        return f"В медиатеке не нашла, ищу «{query}» в Spotify."

    async def _current_volume(self) -> int:
        volume = await _guard(self._system.get_volume())
        if volume is None:
            raise MediaError(NOT_ADJUSTABLE)
        return volume


async def _guard[T](call: Awaitable[T]) -> T:
    """Ждёт системный вызов; отказ macOS и сбой превращает в MediaError с понятным текстом."""
    try:
        return await call
    except PermissionDenied as error:
        raise MediaError(permission_text(error.target)) from None
    except SystemFailure as error:
        raise MediaError(str(error)) from None
