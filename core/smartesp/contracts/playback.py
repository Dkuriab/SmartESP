"""Договор: звуковой файл на колонке — общий механизм (проверка звука, коннекторы), не музыка."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol

# Почему файл не заиграл: колонки нет; не в сети; протокол < 3; занята; файл не разобрать;
# нет ffmpeg или ядро останавливается.
PlaybackRefusal = Literal["unknown_device", "offline", "unsupported", "busy", "undecodable", "unavailable"]


class PlaybackRefused(Exception):
    """Файл не заиграл: reason — причина (для кода ответа), текст исключения — для человека."""

    def __init__(self, reason: PlaybackRefusal, message: str) -> None:
        super().__init__(message)
        self.reason: PlaybackRefusal = reason


class FilePlayback(Protocol):
    """Проигрывание звуковых файлов на колонках; реализует модуль fileplay.

    На колонке — не больше одного файла. Файл играет ходом ядра (как объявление): колонка, приняв
    его, сама играет сигнал «внимание»; слово пробуждения на ней прерывает файл. Начало и итог —
    события playback_started {device_id} и playback_finished {device_id, delivery}.
    """

    async def play_file(self, device_id: str, source: AsyncIterator[bytes]) -> None:
        """Проигрывает файл (MP3, WAV, OGG, M4A, FLAC; байты кусками) на колонке device_id.

        Возвращается, когда колонка начала получать звук; итог придёт событием. Не заиграл —
        PlaybackRefused с причиной.
        """
        ...

    async def stop_file(self, device_id: str) -> bool:
        """Останавливает файл на колонке (итог — interrupted); False — файл не играл.

        Колонки нет — PlaybackRefused("unknown_device").
        """
        ...
