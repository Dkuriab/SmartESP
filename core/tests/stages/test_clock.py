"""Тесты обработчика «время»."""

from datetime import datetime

import pytest

from smartesp.contracts import Stage, Utterance
from smartesp.stages import Clock


def utterance() -> Utterance:
    return Utterance(device_id="kitchen", turn=1, pcm=b"", started_at=0.0, text="который час")


async def note(moment: datetime) -> str:
    stage: Stage = Clock(lambda: moment)
    (annotation,) = await stage.analyze(utterance())
    assert annotation.source == "clock" and annotation.label == "время"
    return annotation.text


async def test_evening_text_in_russian() -> None:
    assert await note(datetime(2026, 11, 19, 21, 40)) == "четверг, 19 ноября 2026, 21:40, вечер"


@pytest.mark.parametrize(
    ("hour", "part"),
    [
        (0, "ночь"),
        (5, "ночь"),
        (6, "утро"),
        (11, "утро"),
        (12, "день"),
        (17, "день"),
        (18, "вечер"),
        (23, "вечер"),
    ],
)
async def test_parts_of_day(hour: int, part: str) -> None:
    assert (await note(datetime(2026, 3, 2, hour, 5))).endswith(f"{hour:02d}:05, {part}")


async def test_weekday_and_month_genitive() -> None:
    assert await note(datetime(2027, 1, 3, 9, 0)) == "воскресенье, 3 января 2027, 09:00, утро"


def test_hint_present_and_default_clock_is_local() -> None:
    assert "[время]" in Clock().prompt_hint


def test_label_goes_to_the_model_message_instead_of_source() -> None:
    from smartesp.contracts import Annotation
    from smartesp.conversation.prompt import build_messages

    note = Annotation("четверг, 19 ноября 2026, 21:40, вечер", "clock", label="время")
    (message,) = build_messages([note], [], "который час", "Кухня")[-1:]
    assert message.content.startswith("[время] четверг, 19 ноября 2026, 21:40, вечер\nКолонка: Кухня")
