"""Тесты пульта: ход через API — текст как есть, голос через разбор звука."""

import pytest
from control_harness import Harness

from smartesp.contracts import Answer, AskUnavailable, AudioUndecodable, Question
from smartesp.control import Core


def core_with(**kwargs: object) -> Core:
    h = Harness()
    return Core(
        h.store,
        {},
        events=h.events,
        feed=h.bus,
        voices=h.voices,
        models=h._models,  # pyright: ignore[reportPrivateUsage]
        loaded=h._loaded,  # pyright: ignore[reportPrivateUsage]
        devices=lambda: [],
        version="1",
        **kwargs,  # pyright: ignore[reportArgumentType]
    )


async def test_ask_and_ask_voice_go_to_turns() -> None:
    asked: list[Question] = []

    async def ask(question: Question) -> Answer:
        asked.append(question)
        return Answer("Ок.", f"api{len(asked)}")

    async def decode(audio: bytes) -> bytes:
        return b"pcm:" + audio

    core = core_with(ask=ask, decode=decode)
    assert await core.ask(Question(text="Привет", person="Аня", source="telegram")) == Answer("Ок.", "api1")
    assert await core.ask_voice(b"ogg", "Аня", "telegram") == Answer("Ок.", "api2")
    assert asked[1] == Question(text="", pcm=b"pcm:ogg", person="Аня", source="telegram")


async def test_undecodable_voice_does_not_start_turn() -> None:
    asked: list[Question] = []

    async def ask(question: Question) -> Answer:
        asked.append(question)
        return Answer("Ок.", "api1")

    async def decode(audio: bytes) -> bytes:
        raise AudioUndecodable("Не получилось разобрать звук")

    with pytest.raises(AudioUndecodable):
        await core_with(ask=ask, decode=decode).ask_voice(b"junk", "", "api")
    assert asked == []


async def test_without_turns_ask_is_unavailable() -> None:
    core = core_with()
    with pytest.raises(AskUnavailable):
        await core.ask(Question(text="Привет"))
    with pytest.raises(AskUnavailable):
        await core.ask_voice(b"ogg", "", "api")
