"""Тесты скачивания голосов (сеть подменена MockTransport)."""

import io
import logging
import zipfile
from pathlib import Path

import httpx
import pytest

import smartesp.tts.download as download_mod
from smartesp.tts import (
    VoiceDownloadError,
    VoiceUnavailableError,
    download_voice,
    ensure_voice,
    is_downloaded,
)

IRINA = "ru_RU-irina-medium"
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/irina/medium/"


def make_zip(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, "{}")
    return buf.getvalue()


def client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


def leftovers(home: Path) -> list[Path]:
    voices = home / "voices"
    return [p for p in voices.rglob("*") if p.is_file() or p.is_dir()] if voices.exists() else []


def test_download_piper_fetches_onnx_and_json(tmp_path: Path) -> None:
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, content=b"a" * 100_000)

    calls: list[tuple[int, int | None]] = []
    download_voice(
        "piper", IRINA, tmp_path, client=client(handler), progress=lambda d, t: calls.append((d, t))
    )
    assert sorted(urls) == [BASE + IRINA + ".onnx", BASE + IRINA + ".onnx.json"]
    assert (tmp_path / "voices" / f"{IRINA}.onnx").exists()
    assert (tmp_path / "voices" / f"{IRINA}.onnx.json").exists()
    assert not list((tmp_path / "voices").glob("*.part"))
    assert calls
    assert calls[-1] == (100_000, 100_000)


def test_download_vosk_unpacks_zip(tmp_path: Path) -> None:
    data = make_zip(["vosk-model-tts-ru-0.9-multi/config.json"])
    download_voice("vosk", "female_1", tmp_path, client=client(lambda r: httpx.Response(200, content=data)))
    assert is_downloaded("vosk", "female_1", tmp_path)
    assert (tmp_path / "voices/vosk/vosk-model-tts-ru-0.9-multi/config.json").exists()
    assert [p.name for p in (tmp_path / "voices" / "vosk").iterdir()] == ["vosk-model-tts-ru-0.9-multi"]


def test_download_silero(tmp_path: Path) -> None:
    seen: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(str(r.url))
        return httpx.Response(200, content=b"pt")

    download_voice("silero", "baya", tmp_path, client=client(handler))
    assert seen == ["https://models.silero.ai/models/tts/ru/v5_ru.pt"]
    assert is_downloaded("silero", "xenia", tmp_path)


def test_zip_slip_rejected(tmp_path: Path) -> None:
    data = make_zip(["vosk-model-tts-ru-0.9-multi/config.json", "../evil.txt"])
    with pytest.raises(VoiceDownloadError):
        download_voice(
            "vosk", "female_0", tmp_path, client=client(lambda r: httpx.Response(200, content=data))
        )
    assert not (tmp_path / "voices" / "evil.txt").exists()
    assert leftovers(tmp_path) == [tmp_path / "voices" / "vosk"] or leftovers(tmp_path) == []


class Dropping(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield b"a" * 70_000
        raise httpx.ReadError("обрыв")


class Stalled(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield b"a" * 10
        raise httpx.ReadTimeout("тишина")


def stall_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, stream=Stalled())


def drop_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, stream=Dropping())


@pytest.mark.parametrize(
    ("kind", "voice", "handler"),
    [
        ("piper", IRINA, lambda r: httpx.Response(404)),
        ("piper", IRINA, drop_handler),
        ("piper", IRINA, stall_handler),
        ("vosk", "female_0", lambda r: httpx.Response(200, content=b"not a zip")),
    ],
)
def test_failed_download_leaves_nothing(tmp_path: Path, kind: str, voice: str, handler) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(VoiceDownloadError):
        download_voice(kind, voice, tmp_path, client=client(handler))
    assert [p for p in leftovers(tmp_path) if p.is_file()] == []
    assert not any(p.name == "vosk-model-tts-ru-0.9-multi" for p in leftovers(tmp_path))
    assert not is_downloaded(kind, voice, tmp_path)


def fake_ok(kind: str, voice: str, home: Path) -> None:
    (home / "voices").mkdir(parents=True, exist_ok=True)
    (home / "voices" / f"{voice}.onnx").write_bytes(b"x")


def fail(kind: str, voice: str, home: Path) -> None:
    raise VoiceDownloadError("нет сети")


def test_ensure_voice_present(tmp_path: Path) -> None:
    fake_ok("piper", IRINA, tmp_path)
    called: list[int] = []
    got = ensure_voice("piper", IRINA, tmp_path, download=lambda *a: called.append(1))
    assert got == ("piper", IRINA)
    assert not called


def test_ensure_voice_downloads(tmp_path: Path) -> None:
    assert ensure_voice("piper", IRINA, tmp_path, download=fake_ok) == ("piper", IRINA)


def test_ensure_voice_falls_back(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    fake_ok("piper", IRINA, tmp_path)
    with caplog.at_level(logging.WARNING):
        got = ensure_voice("silero", "xenia", tmp_path, download=fail)
    assert got == ("piper", IRINA)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_ensure_voice_none_available(tmp_path: Path) -> None:
    with pytest.raises(VoiceUnavailableError, match="интернет"):
        ensure_voice("silero", "xenia", tmp_path, download=fail)


def test_ensure_voice_unknown_voice(tmp_path: Path) -> None:
    called: list[int] = []
    with pytest.raises(ValueError):
        ensure_voice("silero", "aidar", tmp_path, download=lambda *a: called.append(1))
    assert not called


def test_download_timeout_has_read_limit() -> None:
    assert download_mod.TIMEOUT.read == 60.0
    assert download_mod.TIMEOUT.connect == 30.0


def test_download_unsafe_piper_name_rejected(tmp_path: Path) -> None:
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "my_voice.onnx").write_bytes(b"x")
    with pytest.raises(ValueError):
        download_voice("piper", "my_voice", tmp_path, client=client(lambda r: httpx.Response(200)))


def test_ensure_voice_falls_back_to_stray_piper(tmp_path: Path) -> None:
    (tmp_path / "voices").mkdir()
    (tmp_path / "voices" / "my_voice.onnx").write_bytes(b"x")
    assert ensure_voice("silero", "xenia", tmp_path, download=fail) == ("piper", "my_voice")
