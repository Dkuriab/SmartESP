from __future__ import annotations

import time

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


def _wait_zero(bus: EventBus, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if bus.subscriber_count == 0:
            return True
        time.sleep(0.02)
    return False


def test_ws_idle_disconnect_drops_subscription(app: FastAPI, bus: EventBus) -> None:
    with TestClient(app) as client, client.websocket_connect(f"/api/v1/events?token={TOKEN}") as ws:
        deadline = time.monotonic() + 3
        while bus.subscriber_count == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert bus.subscriber_count == 1
        ws.close()  # клиент ушёл, событий не было
        assert _wait_zero(bus)


def test_ws_unserializable_event_does_not_kill_connection(app: FastAPI, bus: EventBus) -> None:
    with TestClient(app) as client, client.websocket_connect(f"/api/v1/events?token={TOKEN}") as ws:
        bus.publish("wake", {"obj": object()})
        first = ws.receive_json()
        assert first["kind"] == "wake"
        assert isinstance(first["data"]["obj"], str)
        bus.publish("wake", {"n": 1})
        assert ws.receive_json()["data"] == {"n": 1}
