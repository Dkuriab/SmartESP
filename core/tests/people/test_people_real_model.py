"""Настоящая модель отпечатков на синтетических голосах Piper (pytest -m models).

Нужна папка данных с моделью и голосами: SMARTESP_TEST_HOME=<папка> (в ней
models/speaker/<модель>.onnx и voices/ru_RU-{irina,denis}-medium.onnx). Не ~/SmartEsp.
"""

import os
import time
from pathlib import Path

import pytest

from smartesp.contracts import Person, VoiceSample
from smartesp.people import OnnxVoicePrint, model_path
from smartesp.people.matching import best_match
from smartesp.tts import PiperTTS, voice_path

ENROLL = ["Кузя, какая сегодня погода?", "Поставь таймер на десять минут.", "Включи свет на кухне."]
CHECK = ["Напомни мне завтра позвонить маме.", "Добавь картошку в список покупок."]


async def _say(tts: PiperTTS, text: str) -> bytes:
    out = bytearray()
    async for chunk in tts.synthesize(text, "normal"):
        out += chunk
    return bytes(out)


def _home() -> Path:
    home = os.environ.get("SMARTESP_TEST_HOME")
    if not home or not model_path(Path(home)).is_file():
        pytest.skip("нет SMARTESP_TEST_HOME с моделью узнавания и голосами Piper")
    return Path(home)


@pytest.mark.models
async def test_two_synthetic_voices_are_told_apart() -> None:
    home = _home()
    printer = OnnxVoicePrint(model_path(home))
    people: list[Person] = []
    checks: list[tuple[str, bytes]] = []
    for name in ("irina", "denis"):
        tts = PiperTTS(voice_path("piper", f"ru_RU-{name}-medium", home))
        prints = [printer.embed(await _say(tts, text)) for text in ENROLL]
        samples = tuple(
            VoiceSample(str(i), 0.0, "A", 2.0, 0.0, printer.model, tuple(v)) for i, v in enumerate(prints)
        )
        people.append(Person(name, name, 0.0, samples))
        checks += [(name, await _say(tts, t)) for t in CHECK]
    for want, pcm in checks:
        started = time.monotonic()
        vector = printer.embed(pcm)
        ms = (time.monotonic() - started) * 1000
        match = best_match(vector, people, printer.model)
        print(f"\n{want}: {match.person.name if match.person else '—'} {match.score:.2f} {ms:.0f} мс")
        assert match.person is not None and match.person.name == want
        assert ms < 100
