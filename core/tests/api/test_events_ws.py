from __future__ import annotations

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from fakes.fake_core import FakeCore
from smartesp.events import EventBus

from .conftest import TOKEN


@pytest.mark.parametrize("query", ["", "?token=wrong", "?token="])
def test_ws_bad_token_closes_4401(app: FastAPI, query: str) -> None:
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as info:
        with client.websocket_connect(f"/api/v1/events{query}") as ws:
            ws.receive_text()
    assert info.value.code == 4401


def test_ws_streams_events_and_unsubscribes(app: FastAPI, bus: EventBus, core: FakeCore) -> None:
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/v1/events?token={TOKEN}") as ws:
            assert bus.subscriber_count == 1
            bus.publish("wake", {"device_id": "d1", "level": 0.5})
            message = ws.receive_json()
            assert set(message) == {"kind", "data", "at"}
            assert message["kind"] == "wake"
            assert message["data"] == {"device_id": "d1", "level": 0.5}
            assert isinstance(message["at"], float)
    assert bus.subscriber_count == 0
