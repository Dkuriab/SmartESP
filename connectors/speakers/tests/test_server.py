"""Инструменты колонок через клиент SDK в памяти; ядро — поддельное (httpx MockTransport)."""

import json

import httpx
from mcp import Client
from mcp.types import RequestParamsMeta, TextContent

from speakers_mcp.core_api import CoreApi
from speakers_mcp.server import build_server

DEVICES = [
    {"device_id": "AA", "name": "Кухня", "connected": True, "volume": 50},
    {"device_id": "BB", "name": "Спальня", "connected": True, "volume": 30},
    {"device_id": "CC", "name": "Балкон", "connected": False, "volume": 50},
]


def fake_core(patches: list[dict[str, object]]) -> CoreApi:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t"
        if request.method == "PATCH":
            patches.append(json.loads(request.content))
            return httpx.Response(200, json={"change_id": 1, "status": "accepted", "error": ""})
        return httpx.Response(200, json={"devices": DEVICES})

    return CoreApi("http://core", "t", transport=httpx.MockTransport(handler))


async def call(
    api: CoreApi, name: str, args: dict[str, object], device: str | None = None
) -> tuple[bool, str]:
    meta = RequestParamsMeta(device=device) if device else None  # type: ignore[call-arg]
    async with Client(build_server(api)) as client:
        result = await client.call_tool(name, args, meta=meta)
    block = result.content[0]
    assert isinstance(block, TextContent)
    return result.is_error, block.text


async def test_list() -> None:
    _, text = await call(fake_core([]), "speakers_list", {})
    assert (
        text
        == "Кухня: в сети, громкость 50 %; Спальня: в сети, громкость 30 %; Балкон: не в сети, громкость 50 %"
    )


async def test_louder_on_the_speaker_you_talk_to() -> None:
    patches: list[dict[str, object]] = []
    assert await call(fake_core(patches), "speaker_volume", {"change": 10}, device="BB") == (
        False,
        "Громкость «Спальня»: 40 % (было 30 %).",
    )
    assert patches == [{"devices": {"BB": {"volume": 40}}}]


async def test_by_name_and_limits_and_query() -> None:
    patches: list[dict[str, object]] = []
    api = fake_core(patches)
    assert (await call(api, "speaker_volume", {"speaker": "кухн", "percent": 150}))[1].startswith(
        "Громкость «Кухня»: 100 %"
    )
    assert await call(api, "speaker_volume", {"speaker": "Спальня"}) == (False, "Громкость «Спальня»: 30 %.")
    assert patches == [{"devices": {"AA": {"volume": 100}}}]


async def test_unknown_or_ambiguous_speaker() -> None:
    error, text = await call(fake_core([]), "speaker_volume", {"speaker": "Гараж", "percent": 10})
    assert error and "Нет колонки «Гараж»" in text and "Кухня" in text
    error, text = await call(
        fake_core([]), "speaker_volume", {"change": 10}
    )  # две в сети, говорят не с колонки
    assert error and "Какую колонку? Есть: Кухня, Спальня." in text


async def test_without_core_env_is_clear_error() -> None:
    error, text = await call(CoreApi("", ""), "speakers_list", {})
    assert error and "нет адреса или токена ядра" in text
