from fakes.fake_executor import FakeExecutor
from fakes.fake_stt import FakeSTT
from fakes.fake_tts import FakeTTS
from smartesp.contracts.executor import Executor
from smartesp.contracts.stt import SpeechToText
from smartesp.contracts.tts import TextToSpeech


async def test_fakes_satisfy_contracts() -> None:
    stt: SpeechToText = FakeSTT("привет")
    tts: TextToSpeech = FakeTTS()
    executor: Executor = FakeExecutor(["а", "б"])

    assert await stt.transcribe(b"") == "привет"
    assert [p.text async for p in executor.run([])] == ["а", "б"]
    assert tts.styles() == ["normal"]
    chunks = [c async for c in tts.synthesize("Один. Два.", "normal")]
    assert len(chunks) == 2
    assert all(len(c) % 2 == 0 for c in chunks)
