"""Тесты обработчика «время»."""

from datetime import datetime

from smartesp.contracts import Annotation, Stage, Utterance
from smartesp.stages import Clock


def utterance() -> Utterance:
    return Utterance(device_id="kitchen", turn=1, pcm=b"", started_at=0.0, text="который час")


async def note(moment: datetime) -> str:
    stage: Stage = Clock(lambda: moment)
    (annotation,) = await stage.analyze(utterance())
    assert annotation.source == "clock" and annotation.label == "время"
    return annotation.text


async def test_text_in_russian_without_part_of_day() -> None:
    assert await note(datetime(2026, 11, 19, 21, 40)) == "четверг, 19 ноября 2026, 21:40"


async def test_weekday_and_month_genitive() -> None:
    assert await note(datetime(2027, 1, 3, 9, 0)) == "воскресенье, 3 января 2027, 09:00"


async def test_note_is_reference_not_a_remark() -> None:
    (annotation,) = await Clock(lambda: datetime(2026, 1, 1)).analyze(utterance())
    assert annotation.reference


def test_no_prompt_hint_reference_explains_itself() -> None:
    assert Clock().prompt_hint == ""


def test_clock_goes_to_the_reference_line() -> None:
    from smartesp.conversation.prompt import REFERENCE_HEAD, build_messages

    note = Annotation("четверг, 19 ноября 2026, 21:40", "clock", label="время", reference=True)
    reference, _ = build_messages([note], [], "который час", "Кухня")
    assert reference.content == f"{REFERENCE_HEAD} время — четверг, 19 ноября 2026, 21:40; колонка — Кухня."
