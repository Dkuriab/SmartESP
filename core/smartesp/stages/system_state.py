"""Обработчик «система»: справка о том, что сейчас в работе и какие навыки подключены.

Без неё модель не знает, что таймер уже идёт или Клод ещё думает, и не знает своих
навыков — гадает или говорит, что не умеет. Пометка справочная (reference): модель
пользуется ею, когда спросили «что сейчас делается?» или «что ты умеешь?», и не
пересказывает её без вопроса. Данные даёт связка через SYSTEM_FACTS (у обработчика нет
доступа к реестру задач и коннекторам — модули друг друга не знают).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from smartesp.contracts import Annotation, Utterance

TASKS_LABEL = "в работе"
SKILLS_LABEL = "навыки"
VOLUME_LABEL = "громкость колонок"
_MAX_TASKS = 5  # больше — «и ещё N»: справка не должна раздувать промпт


@dataclass(frozen=True)
class SystemSnapshot:
    """Что сейчас в системе: идущие задачи (название, срок time.time() или None) и навыки."""

    tasks: list[tuple[str, float | None]] = field(default_factory=lambda: list[tuple[str, float | None]]())
    skills: list[str] = field(default_factory=lambda: list[str]())
    volumes: list[tuple[str, int]] = field(default_factory=lambda: list[tuple[str, int]]())  # колонка, %


class SystemFacts:
    """Источник снимка системы; связка задаёт его через use(), до этого снимок пустой."""

    def __init__(self) -> None:
        """Пустой источник."""
        self._source: Callable[[], SystemSnapshot] = SystemSnapshot

    def use(self, source: Callable[[], SystemSnapshot]) -> None:
        """Задаёт, откуда брать снимок (вызывается связкой после сборки частей)."""
        self._source = source

    def snapshot(self) -> SystemSnapshot:
        """Текущий снимок системы."""
        return self._source()


SYSTEM_FACTS = SystemFacts()  # один на процесс: задаёт связка (wiring), читает обработчик


def _left(eta: float | None, now: float) -> str:
    """« (ещё 5 мин)», « (вот-вот)» или пусто, если срока нет."""
    if eta is None:
        return ""
    minutes = round((eta - now) / 60)
    return " (вот-вот)" if minutes <= 0 else f" (ещё {minutes} мин)"


def describe_tasks(tasks: list[tuple[str, float | None]], now: float) -> str:
    """«таймер «картошка» (ещё 5 мин), ответ модели» — не больше _MAX_TASKS, дальше «и ещё N»."""
    items = [f"{title}{_left(eta, now)}" for title, eta in tasks[:_MAX_TASKS]]
    if len(tasks) > _MAX_TASKS:
        items.append(f"и ещё {len(tasks) - _MAX_TASKS}")
    return ", ".join(items)


class SystemState:
    """Добавляет к фразе справку: что в работе (или «ничего»), какие навыки подключены и громкость
    подключённых колонок."""

    name = "system"
    prompt_hint = ""  # справка объясняет себя сама (conversation/prompt.py)

    def __init__(self, facts: SystemFacts = SYSTEM_FACTS, now: Callable[[], float] = time.time) -> None:
        """facts — источник снимка; now — часы для сроков (в тестах подменяются)."""
        self._facts = facts
        self._now = now

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Две справочные пометки: «в работе — …» и «навыки — …» (вторая — если навыки есть)."""
        snap = self._facts.snapshot()
        tasks = describe_tasks(snap.tasks, self._now()) or "ничего"
        notes = [Annotation(text=tasks, source=self.name, label=TASKS_LABEL, reference=True)]
        if snap.skills:
            skills = ", ".join(snap.skills)
            notes.append(Annotation(text=skills, source=self.name, label=SKILLS_LABEL, reference=True))
        if snap.volumes:
            volumes = ", ".join(f"{name} {percent} %" for name, percent in snap.volumes)
            notes.append(Annotation(text=volumes, source=self.name, label=VOLUME_LABEL, reference=True))
        return notes
