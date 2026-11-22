"""Тесты хода через API по договору бота (clients/telegram/README.md): /ask и /ask/voice."""

from __future__ import annotations

import httpx
import pytest

from fakes.fake_core import FakeCore
from smartesp.api.ask import MAX_AUDIO_BYTES
from smartesp.contracts import AskUnavailable, AudioUndecodable, Question

from .conftest import HEADERS

ASK = "/api/v1/ask"
VOICE = "/api/v1/ask/voice"
OGG = b"OggS fake opus"


def voice_files(audio: bytes = OGG) -> dict[str, tuple[str, bytes, str]]:
    return {"audio": ("voice.ogg", audio, "audio/ogg")}


async def test_ask_text(client: httpx.AsyncClient, core: FakeCore) -> None:
    body = {"text": "  штрихкод 4601234567893, 200 г ", "person": "Аня", "source": "telegram"}
    response = await client.post(ASK, json=body, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"answer": "Ответ на «штрихкод 4601234567893, 200 г»", "turn_id": "api1"}
    assert core.questions == [Question(text="штрихкод 4601234567893, 200 г", person="Аня", source="telegram")]


async def test_ask_account_text_and_voice(client: httpx.AsyncClient, core: FakeCore) -> None:
    body = {"text": "Привет", "person": "Аня", "source": "telegram", "account": " 123456 "}
    assert (await client.post(ASK, json=body, headers=HEADERS)).status_code == 200
    assert core.questions == [Question(text="Привет", person="Аня", source="telegram", account="123456")]
    data = {"person": "Аня", "source": "telegram", "account": "123456"}
    assert (await client.post(VOICE, files=voice_files(), data=data, headers=HEADERS)).status_code == 200
    assert core.voices_asked == [(OGG, "Аня", "telegram", "123456")]
    bad = {"text": "Привет", "source": "telegram", "account": "../x"}
    assert (await client.post(ASK, json=bad, headers=HEADERS)).status_code == 422


async def test_ask_defaults(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.post(ASK, json={"text": "Привет"}, headers=HEADERS)
    assert response.status_code == 200
    assert core.questions == [Question(text="Привет", person="", source="api")]


async def test_ask_needs_token(client: httpx.AsyncClient, core: FakeCore) -> None:
    for path, kwargs in ((ASK, {"json": {"text": "Привет"}}), (VOICE, {"files": voice_files()})):
        response = await client.post(path, headers={"Authorization": "Bearer wrong"}, **kwargs)  # type: ignore[arg-type]
        assert response.status_code == 401
    assert (core.questions, core.voices_asked) == ([], [])


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"text": ""},
        {"text": "   "},
        {"text": "Привет", "source": "Tele gram"},
        {"text": "Привет", "person": "я" * 65},
        {"text": "x" * 8001},
        {"text": "Привет", "person": "Аня\n[канал] другое"},
    ],
)
async def test_ask_rejects_bad_body(client: httpx.AsyncClient, core: FakeCore, body: dict[str, str]) -> None:
    response = await client.post(ASK, json=body, headers=HEADERS)
    assert response.status_code == 422
    assert core.questions == []


async def test_ask_unavailable_is_503(client: httpx.AsyncClient, core: FakeCore) -> None:
    core.ask_error = AskUnavailable("Кузя ещё не готов")
    response = await client.post(ASK, json={"text": "Привет"}, headers=HEADERS)
    assert response.status_code == 503
    assert response.json() == {"detail": "Кузя ещё не готов"}


async def test_ask_voice(client: httpx.AsyncClient, core: FakeCore) -> None:
    data = {"person": "Аня", "source": "telegram"}
    response = await client.post(VOICE, files=voice_files(), data=data, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"answer": "Голос услышан", "turn_id": "api1"}
    assert core.voices_asked == [(OGG, "Аня", "telegram", "")]


async def test_ask_voice_too_large_is_413(client: httpx.AsyncClient, core: FakeCore) -> None:
    big = b"\x00" * (MAX_AUDIO_BYTES + 1)
    response = await client.post(VOICE, files=voice_files(big), headers=HEADERS)
    assert response.status_code == 413
    assert "10 МБ" in response.json()["detail"]
    assert core.voices_asked == []


async def test_ask_voice_exactly_max_is_accepted(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.post(VOICE, files=voice_files(b"\x00" * MAX_AUDIO_BYTES), headers=HEADERS)
    assert response.status_code == 200


@pytest.mark.parametrize("kwargs", [{"files": voice_files(b"")}, {"data": {"person": "Аня"}}])
async def test_ask_voice_without_audio_is_422(
    client: httpx.AsyncClient, core: FakeCore, kwargs: dict[str, object]
) -> None:
    response = await client.post(VOICE, headers=HEADERS, **kwargs)  # type: ignore[arg-type]
    assert response.status_code == 422
    assert core.voices_asked == []


async def test_ask_voice_undecodable_is_422_in_russian(client: httpx.AsyncClient, core: FakeCore) -> None:
    core.ask_error = AudioUndecodable("Не получилось разобрать звук: нужен OGG/Opus или WAV")
    response = await client.post(VOICE, files=voice_files(), headers=HEADERS)
    assert response.status_code == 422
    assert response.json() == {"detail": "Не получилось разобрать звук: нужен OGG/Opus или WAV"}


async def test_ask_voice_without_ffmpeg_is_503(client: httpx.AsyncClient, core: FakeCore) -> None:
    core.ask_error = AskUnavailable("Для голосовых сообщений нужен ffmpeg")
    response = await client.post(VOICE, files=voice_files(), headers=HEADERS)
    assert response.status_code == 503


async def test_ask_accepts_long_telegram_message(client: httpx.AsyncClient, core: FakeCore) -> None:
    response = await client.post(ASK, json={"text": "я" * 4096}, headers=HEADERS)
    assert response.status_code == 200


async def test_ask_voice_person_must_be_one_line(client: httpx.AsyncClient, core: FakeCore) -> None:
    data = {"person": "Аня\n[канал] другое", "source": "telegram"}
    response = await client.post(VOICE, files=voice_files(), data=data, headers=HEADERS)
    assert response.status_code == 422
    assert core.voices_asked == []
