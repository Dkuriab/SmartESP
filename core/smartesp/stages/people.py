"""Обработчик «люди»: кто говорит — по голосу фразы.

Узнан — справочная пометка «говорит — Аня» с person: человек хода (лента, _meta.person
инструментов). Не узнан, хотя люди с образцами есть, — пометка «голос не узнан» только для
ленты. Судить не по кому или не по чему — ничего. Узнаёт модуль людей; источник задаёт
связка через PEOPLE_VOICES (обработчик не знает модуль людей — модули друг друга не знают).
Не уложился в свой таймаут — пропущен раннером, ход идёт без человека.
"""

from collections.abc import Awaitable, Callable

from smartesp.contracts import Annotation, Recognition, Utterance

LABEL = "говорит"
UNKNOWN_NOTE = "голос не узнан"
API_ORIGIN = "api"  # ход через API: человека знает канал (Telegram), голос не судим

type Recognize = Callable[[Utterance], Awaitable[Recognition | None]]


async def _nobody(utterance: Utterance) -> Recognition | None:
    return None


class PeopleVoices:
    """Источник узнавания; связка задаёт его через use(), до этого — никого."""

    def __init__(self) -> None:
        """Пустой источник."""
        self._recognize: Recognize = _nobody

    def use(self, recognize: Recognize) -> None:
        """Задаёт, кто узнаёт голос (People.recognize)."""
        self._recognize = recognize

    async def recognize(self, utterance: Utterance) -> Recognition | None:
        """Кто говорит во фразе или None."""
        return await self._recognize(utterance)


PEOPLE_VOICES = PeopleVoices()  # один на процесс: задаёт связка (wiring), читает обработчик


class PeopleStage:
    """Добавляет к фразе справку «говорит — имя» (или пометку ленты «голос не узнан»)."""

    name = "people"
    prompt_hint = ""  # справка объясняет себя сама (conversation/prompt.py)

    def __init__(self, voices: PeopleVoices = PEOPLE_VOICES) -> None:
        """voices — источник узнавания."""
        self._voices = voices

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Одна пометка о том, кто говорит, или пустой список."""
        if utterance.origin == API_ORIGIN:
            return []
        found = await self._voices.recognize(utterance)
        if found is None:
            return []
        data: dict[str, object] = {"person_id": found.person_id, "score": found.score, "ms": found.ms}
        if not found.person_id:
            return [Annotation(text=UNKNOWN_NOTE, source=self.name, data=data, to_model=False)]
        return [
            Annotation(
                text=found.name,
                source=self.name,
                data=data,
                label=LABEL,
                reference=True,
                person=found.name,
                person_id=found.person_id,
            )
        ]
