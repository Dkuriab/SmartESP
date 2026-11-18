"""Тесты стиля озвучки: метка в ответе модели снимается и доходит до озвучки."""

from collections.abc import AsyncIterator

import pytest
from conversation_helpers import CountingTTS, Setup, make_utterance, running, wait_for

from fakes.fake_executor import FakeExecutor
from smartesp.contracts import ChatMessage
from smartesp.conversation import take_style

STYLES = ["normal", "quiet"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("[style:quiet] Говорю тихо.", ("quiet", "Говорю тихо.")),
        ("[Style: QUIET]Говорю тихо.", ("quiet", "Говорю тихо.")),
        ("Обычный ответ.", ("normal", "Обычный ответ.")),
        ("[style:loud] Громко!", ("normal", "Громко!")),
        ("\n [style:quiet]\nТихо.", ("quiet", "Тихо.")),
        ("[style:quiet-2] Тихо.", ("normal", "Тихо.")),
        ("Текст [style:quiet] в середине.", ("normal", "Текст [style:quiet] в середине.")),
    ],
)
def test_take_style(text: str, expected: tuple[str, str]) -> None:
    assert take_style(text, STYLES) == expected


class StyledTTS(CountingTTS):
    """CountingTTS с двумя стилями, запоминает стиль каждого вызова."""

    def __init__(self) -> None:
        super().__init__()
        self.used: list[str] = []

    def styles(self) -> list[str]:
        return list(STYLES)

    def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        self.used.append(style)
        return super().synthesize(text, style)


async def test_model_style_tag_reaches_tts_and_is_hidden() -> None:
    executor = FakeExecutor(["[sty", "le:quiet] Тише, все спят. ", "Завтра будет солнечно."])
    tts = StyledTTS()
    setup = Setup(executor, tts=tts)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert tts.used == ["quiet", "quiet"]
    assert tts.texts == ["Тише, все спят.", "Завтра будет солнечно."]
    assert setup.history.messages()[-1] == ChatMessage("assistant", "Тише, все спят. Завтра будет солнечно.")


async def test_no_tag_means_normal_style() -> None:
    tts = StyledTTS()
    setup = Setup(FakeExecutor(["Обычный ответ без метки."]), tts=tts)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert tts.used == ["normal"]


async def test_tag_only_reply_is_empty_answer() -> None:
    tts = StyledTTS()
    setup = Setup(FakeExecutor(["[style:quiet]"]), tts=tts)
    setup.port.feed(make_utterance())
    async with running(setup):
        await wait_for(lambda: setup.port.wait_plays(1))
    assert tts.texts == []
    assert setup.port.tones == [("kitchen", "error")]
    assert setup.history.messages() == []
