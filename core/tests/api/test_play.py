"""Тесты файла на колонке через API: POST и DELETE /devices/{id}/play с подделкой проигрывания."""

from __future__ import annotations

import httpx
import pytest

from fakes.fake_playback import FakeFilePlayback
from smartesp.contracts import PlaybackRefusal, PlaybackRefused

from .conftest import HEADERS

MAC = "aa:bb:cc:dd:ee:ff"
URL = f"/api/v1/devices/{MAC}/play"


def song(data: bytes = b"ID3 fake") -> dict[str, tuple[str, bytes, str]]:
    return {"audio": ("song.mp3", data, "audio/mpeg")}


async def test_play_starts(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    response = await client.post(URL, files=song(), headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {"status": "started"}
    assert files.plays == [(MAC, b"ID3 fake")]


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("unknown_device", 404),
        ("offline", 409),
        ("unsupported", 409),
        ("busy", 409),
        ("undecodable", 422),
        ("unavailable", 503),
    ],
)
async def test_play_refusals(
    client: httpx.AsyncClient, files: FakeFilePlayback, reason: PlaybackRefusal, code: int
) -> None:
    files.error = PlaybackRefused(reason, "Колонка занята")
    response = await client.post(URL, files=song(), headers=HEADERS)
    assert response.status_code == code
    assert response.json() == {"detail": "Колонка занята"}


async def test_empty_file_is_422(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    response = await client.post(URL, files=song(b""), headers=HEADERS)
    assert response.status_code == 422
    assert files.plays == []


async def test_play_needs_token(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    assert (await client.post(URL, files=song())).status_code == 401
    assert (await client.delete(URL)).status_code == 401
    assert (files.plays, files.stops) == ([], [])


async def test_stop(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    response = await client.delete(URL, headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"stopped": True}
    files.stopped = False
    assert (await client.delete(URL, headers=HEADERS)).json() == {"stopped": False}
    assert files.stops == [MAC, MAC]


async def test_stop_unknown_device_is_404(client: httpx.AsyncClient, files: FakeFilePlayback) -> None:
    files.error = PlaybackRefused("unknown_device", "Колонка не найдена")
    response = await client.delete(URL, headers=HEADERS)
    assert response.status_code == 404
    assert response.json() == {"detail": "Колонка не найдена"}
