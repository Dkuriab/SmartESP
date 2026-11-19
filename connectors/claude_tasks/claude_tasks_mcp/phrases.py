"""Русские фразы для озвучки: имена задач, ответы инструментов, объявления."""

import re
from datetime import datetime

from claude_tasks_mcp.record import TaskRecord
from claude_tasks_mcp.speech import duration, plural, sentence_end, summarize

DEFAULT_NAME = "задача"
NAME_WORDS = 4
NAME_CHARS = 40
NO_TASKS = "Задач для Клода ещё не было."
DENIED = "Часть действий Клоду не разрешили."

_WORD = re.compile(r"[\w-]+")
_TASK = ("задача", "задачи", "задач")


def make_name(prompt: str) -> str:
    """Короткое имя задачи для речи: первые слова текста в нижнем регистре."""
    words = _WORD.findall(prompt.lower())[:NAME_WORDS]
    name = " ".join(words)[:NAME_CHARS].strip()
    return name or DEFAULT_NAME


def unique_name(base: str, taken: list[str]) -> str:
    """Имя без повторов (без учёта регистра): «задача», «задача 2», «задача 3»…"""
    used = {name.casefold() for name in taken}
    if base.casefold() not in used:
        return base
    n = 2
    while f"{base} {n}".casefold() in used:
        n += 1
    return f"{base} {n}"


def _elapsed(record: TaskRecord, now: datetime) -> float:
    end = record.finished or now
    return (end - record.started).total_seconds()


def started_text(record: TaskRecord) -> str:
    """Ответ на запуск задачи."""
    return f"Передала Клоду: «{record.name}». Скажу, когда закончит."


def busy_text(limit: int) -> str:
    """Отказ, когда уже идёт предельное число задач."""
    return f"Уже идут {plural(limit, _TASK)} Клода — больше нельзя. Подожди или отмени одну."


def timeout_reason(seconds: float) -> str:
    """Причина ошибки, когда задача не уложилась в предел времени."""
    if seconds < 60:
        return "не уложился в отведённое время"
    return f"не уложился в {duration(seconds, accusative=True)}"


def status_text(record: TaskRecord, now: datetime) -> str:
    """Состояние задачи со временем."""
    title = f"Задача «{record.name}»"
    if record.status == "running":
        return f"{title} идёт {duration(_elapsed(record, now))}."
    if record.status == "done":
        how = "готова с отказами" if record.denials else "готова"
        return f"{title} {how} за {duration(_elapsed(record, now), accusative=True)}."
    if record.status == "failed":
        return f"{title}: ошибка — {sentence_end(record.error)}"
    return f"{title} отменена."


def _short_state(record: TaskRecord, now: datetime) -> str:
    if record.status == "running":
        return f"идёт {duration(_elapsed(record, now))}"
    if record.status == "done" and record.denials:
        return "готово с отказами"
    return {"done": "готово", "failed": "ошибка", "cancelled": "отменена"}[record.status]


def list_text(records: list[TaskRecord], now: datetime) -> str:
    """Список последних задач (новые первыми)."""
    if not records:
        return NO_TASKS
    items = "; ".join(f"{r.name} — {_short_state(r, now)}" for r in records)
    return f"Задачи Клода: {items}."


def failed_text(record: TaskRecord) -> str:
    """Задача не удалась: причина."""
    return sentence_end(f"Клод не справился с «{record.name}»: {record.error}")


def result_text(record: TaskRecord) -> str:
    """Короткий итог задачи: 2–3 первых предложения ответа Claude."""
    if record.status == "running":
        return f"Клод ещё работает над «{record.name}»."
    if record.status == "failed":
        return failed_text(record)
    if record.status == "cancelled":
        return f"Задача «{record.name}» была отменена."
    return record.summary or f"Клод закончил «{record.name}» без ответа."


def cancel_text(record: TaskRecord, was_running: bool) -> str:
    """Ответ на отмену."""
    if was_running:
        return f"Задача «{record.name}» отменена."
    return f"Задача «{record.name}» уже не идёт."


def with_denials(text: str, record: TaskRecord) -> str:
    """Текст с пометкой «Часть действий Клоду не разрешили.», если были отказы."""
    if not record.denials:
        return text
    return f"{sentence_end(text)} {DENIED}".strip()


def done_announce(record: TaskRecord, answer: str) -> str:
    """Объявление о готовой задаче: одна фраза итога (и пометка об отказах)."""
    phrase = summarize(answer, 1, max_chars=200)
    if not phrase:
        return with_denials(f"Клод закончил «{record.name}».", record)
    return with_denials(sentence_end(f"Клод закончил «{record.name}»: {phrase.rstrip('.')}"), record)


def ambiguous_text(names: list[str]) -> str:
    """Просьба уточнить, о какой задаче речь."""
    return "Уточни: " + ", ".join(f"«{n}»" for n in names) + "."
