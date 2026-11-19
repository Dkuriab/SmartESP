"""Договор с системой Mac: всё, что трогает ОС, идёт через MediaSystem.

Логика инструментов работает только с этим протоколом, поэтому в тестах её
можно проверить подделкой: настоящая громкость, клавиши и устройства не меняются.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

# Медиа-клавиша: «плей/пауза», следующий и предыдущий трек.
MediaKey = Literal["play_pause", "next", "previous"]

# Плеер, которым коннектор умеет управлять через AppleScript.
Player = Literal["Music", "Spotify"]

# Кому нужно разрешение macOS: плееру (Автоматизация) или нажатию клавиш (Универсальный доступ).
PermissionTarget = Literal["Music", "Spotify", "keys"]


@dataclass(frozen=True)
class Track:
    """Трек: название, исполнитель (может быть пустым) и играет ли он сейчас."""

    name: str
    artist: str = ""
    playing: bool = True


class PermissionDenied(Exception):
    """macOS не дала разрешения: target — чем не дали управлять."""

    def __init__(self, target: PermissionTarget) -> None:
        super().__init__(target)
        self.target: PermissionTarget = target


class SystemFailure(Exception):
    """Системный вызов не удался; текст — короткий, по-русски, для ответа."""


class MediaSystem(Protocol):
    """Тонкий слой над macOS. Ошибки — PermissionDenied или SystemFailure."""

    async def press_media_key(self, key: MediaKey) -> None:
        """Нажимает системную медиа-клавишу key (работает с любым плеером)."""
        ...

    async def get_volume(self) -> int | None:
        """Громкость выхода 0–100; None — у устройства громкость не регулируется."""
        ...

    async def set_volume(self, percent: int) -> None:
        """Ставит громкость выхода percent (уже проверено: целое 0–100)."""
        ...

    async def output_devices(self) -> list[str]:
        """Имена устройств вывода звука."""
        ...

    async def default_output(self) -> str | None:
        """Имя текущего устройства вывода; None — не удалось узнать."""
        ...

    async def set_default_output(self, name: str) -> None:
        """Делает устройство с точным именем name устройством вывода."""
        ...

    async def running_players(self) -> list[Player]:
        """Какие из известных плееров сейчас запущены."""
        ...

    async def now_playing(self, player: Player) -> Track | None:
        """Текущий трек запущенного плеера; None — ничего не выбрано или остановлено."""
        ...

    async def spotify_installed(self) -> bool:
        """Установлен ли Spotify."""
        ...

    async def music_search_play(self, query: str) -> Track | None:
        """Ищет query в медиатеке Music и включает первое совпадение; None — не нашлось."""
        ...

    async def spotify_search_play(self, query: str) -> None:
        """Просит Spotify найти и включить query."""
        ...
