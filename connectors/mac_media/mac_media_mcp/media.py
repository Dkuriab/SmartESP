"""Логика инструментов: проверка параметров и короткие русские ответы для озвучки.

С ОС работает только через MediaSystem; каждый инструмент укладывается в бюджет
времени (budget.py); ошибки для человека — MediaError.
"""

import asyncio

from mac_media_mcp.budget import BUDGET_S, Budget, MediaError
from mac_media_mcp.system import MediaKey, MediaSystem, Player, Track

__all__ = ["BUDGET_S", "MediaError", "MediaService"]

NOTHING_PLAYING = "Не вижу, что сейчас играет."
NOT_ADJUSTABLE = "У этого устройства вывода громкость не регулируется."

_KEY_ANSWERS: dict[MediaKey, str] = {
    "play_pause": "Переключила воспроизведение.",
    "next": "Следующий трек.",
    "previous": "Предыдущий трек.",
}


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


def match_device(devices: list[str], name: str) -> tuple[str | None, list[str]]:
    """Точное совпадение без регистра (или None) и устройства, у которых name — лишь часть имени."""
    wanted = _key(name)
    exact = next((device for device in devices if _key(device) == wanted), None)
    if exact is not None:
        return exact, []
    return None, [device for device in devices if wanted and wanted in _key(device)]


class MediaService:
    """Инструменты коннектора над системой Mac; budget_s — время на один инструмент."""

    def __init__(self, system: MediaSystem, budget_s: float = BUDGET_S) -> None:
        self._system = system
        self._budget_s = budget_s

    def _budget(self) -> Budget:
        return Budget(self._budget_s)

    async def press(self, key: MediaKey) -> str:
        """Нажимает медиа-клавишу и говорит, что сделано."""
        await self._budget().run(lambda: self._system.press_media_key(key))
        return _KEY_ANSWERS[key]

    async def now_playing(self) -> str:
        """Что играет в запущенных плеерах (их спрашиваем разом); играющий важнее паузы.

        Ничего не нашлось, а плеер отказал или молчит — честно об этом, а не «ничего не играет».
        """
        budget = self._budget()
        players = await budget.run(self._system.running_players)
        results = await asyncio.gather(*(self._ask(budget, player) for player in players))
        tracks = sorted((r for r in results if isinstance(r, Track)), key=lambda track: not track.playing)
        if tracks:
            prefix = "Сейчас играет" if tracks[0].playing else "На паузе"
            return f"{prefix}: {track_text(tracks[0])}."
        errors = sorted(
            (r for r in results if isinstance(r, MediaError)),
            key=lambda error: not error.permission,
        )
        if errors:
            raise errors[0]
        return NOTHING_PLAYING

    async def _ask(self, budget: Budget, player: Player) -> Track | MediaError | None:
        try:
            return await budget.run(lambda: self._system.now_playing(player), player)
        except MediaError as error:
            return error

    async def volume_get(self) -> str:
        """Текущая громкость выхода."""
        return f"Громкость {percent_text(await self._current_volume(self._budget()))}."

    async def volume_set(self, percent: int) -> str:
        """Ставит громкость: только целое от 0 до 100."""
        if not 0 <= percent <= 100:
            raise MediaError("Громкость — от 0 до 100 процентов.")
        await self._budget().run(lambda: self._system.set_volume(percent))
        return f"Громкость {percent_text(percent)}."

    async def volume_change(self, delta: int) -> str:
        """Громче или тише на delta процентов; за пределы 0–100 не выходит."""
        if not -100 <= delta <= 100:
            raise MediaError("Изменение громкости — от -100 до 100 процентов.")
        budget = self._budget()
        current = await self._current_volume(budget)
        target = max(0, min(100, current + delta))
        if target == current and delta > 0:
            return "Громкость уже на максимуме."
        if target == current and delta < 0:
            return "Звук уже выключен."
        await budget.run(lambda: self._system.set_volume(target))
        return f"Громкость {percent_text(target)}."

    async def output_devices(self) -> str:
        """Список устройств вывода, текущее помечено «(сейчас)»."""
        budget = self._budget()
        devices = await budget.run(self._system.output_devices)
        if not devices:
            return "Не вижу устройств вывода звука."
        current = await budget.run(self._system.default_output)
        names = [f"{device} (сейчас)" if device == current else device for device in devices]
        return f"Устройства вывода: {', '.join(names)}."

    async def output_set(self, name: str) -> str:
        """Переключает вывод только на устройство с точным именем (без регистра и «ё»).

        По части имени не переключает, а переспрашивает «Уточни: …?»: модель зовёт инструмент и
        без просьбы («включи свет на кухне» → «кухня»), а звук не должен уходить на чужое устройство.
        """
        budget = self._budget()
        devices = await budget.run(self._system.output_devices)
        device, similar = match_device(devices, name)
        if device is None and not similar:
            listed = ", ".join(devices) if devices else "ничего"
            raise MediaError(f"Не нашла устройство «{name.strip()}». Есть: {listed}.")
        if device is None:
            if len(similar) == 1:
                return f"Уточни: это {similar[0]}?"
            return f"Уточни: {', '.join(similar[:-1])} или {similar[-1]}?"
        if device == await budget.run(self._system.default_output):
            return f"Звук и так идёт через {device}."
        await budget.run(lambda: self._system.set_default_output(device))
        return f"Звук теперь через {device}."

    async def music_play(self, query: str) -> str:
        """Ищет в медиатеке Music и включает; не нашлось — Spotify, если он есть."""
        query = query.strip()
        if not query:
            raise MediaError("Скажи, что включить.")
        budget = self._budget()
        track = await budget.run(lambda: self._system.music_search_play(query), "Music")
        if track is not None:
            return f"Включаю: {track_text(track)}."
        if not await budget.run(self._system.spotify_installed, "Spotify"):
            return f"В медиатеке не нашла «{query}»."
        await budget.run(lambda: self._system.spotify_search_play(query), "Spotify")
        return f"В медиатеке не нашла, ищу «{query}» в Spotify."

    async def _current_volume(self, budget: Budget) -> int:
        volume = await budget.run(self._system.get_volume)
        if volume is None:
            raise MediaError(NOT_ADJUSTABLE)
        return volume
