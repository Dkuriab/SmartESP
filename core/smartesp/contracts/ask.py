"""Договор: ход через API — вопрос текстом или голосом, ответ текстом."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Question:
    """Вопрос через API.

    text — вопрос текстом; пусто — голосовой вопрос, его звук в pcm (s16le, 16 кГц, моно;
    пустой pcm — в голосовом нечего распознать). person — кто спрашивает ("" — неизвестно);
    source — откуда вопрос ("telegram"), для ленты.
    """

    text: str = ""
    pcm: bytes = b""
    person: str = ""
    source: str = "api"


@dataclass(frozen=True)
class Answer:
    """Ответ на вопрос через API: текст и номер хода в ленте."""

    text: str
    turn_id: str


class AskUnavailable(Exception):
    """Ход через API сейчас невозможен: ядро не готово, останавливается или нет нужной программы."""


class AudioUndecodable(Exception):
    """Звук не разобрать: не OGG/Opus или WAV, испорчен или пуст."""
