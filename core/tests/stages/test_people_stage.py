"""Тесты обработчика «люди»: справка «говорит — имя», пометка ленты, ходы через API."""

import asyncio

from smartesp.contracts import Recognition, Stage, Utterance
from smartesp.conversation import build_messages
from smartesp.stages import PeopleStage, run_stages
from smartesp.stages.people import PeopleVoices


def _utterance(origin: str = "wake") -> Utterance:
    return Utterance("kitchen", 3, b"\x00\x00" * 32000, 0.0, origin=origin)


def _voices(person_id: str, name: str, delay_s: float = 0.0) -> PeopleVoices:
    voices = PeopleVoices()

    async def recognize(utterance: Utterance) -> Recognition | None:
        await asyncio.sleep(delay_s)
        return Recognition(1.0, utterance.device_id, utterance.turn, person_id, name, 0.8, 15.0)

    voices.use(recognize)
    return voices


async def test_known_voice_is_reference_with_person() -> None:
    stage: Stage = PeopleStage(_voices("a1", "Аня"))
    (note,) = await stage.analyze(_utterance())
    assert (note.text, note.label, note.person, note.reference, note.to_model) == (
        "Аня",
        "говорит",
        "Аня",
        True,
        True,
    )
    assert note.data == {"person_id": "a1", "score": 0.8, "ms": 15.0}
    messages = build_messages([note], [], "привет", "Кухня")
    assert "говорит — Аня" in messages[0].content


async def test_unknown_voice_only_for_feed() -> None:
    (note,) = await PeopleStage(_voices("", "")).analyze(_utterance())
    assert note.text == "голос не узнан" and not note.to_model and note.person == ""


async def test_nothing_without_source_or_for_api_turns() -> None:
    assert await PeopleStage(PeopleVoices()).analyze(_utterance()) == []
    assert await PeopleStage(_voices("a1", "Аня")).analyze(_utterance("api")) == []


async def test_slow_recognition_is_skipped_by_timeout() -> None:
    stage = PeopleStage(_voices("a1", "Аня", delay_s=1.0))
    assert await run_stages([(stage, 0.05)], _utterance()) == []
