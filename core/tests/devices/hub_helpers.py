"""Общие помощники тестов хаба: подставные часы, ожидание условия, подключение колонки."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

from fakes.fake_connection import FakeConnection
from smartesp.devices import DeviceHub

WINDOW_S = 0.3
LATE_S = 1.5
FRAME = bytes(1024)  # кадр колонки: 512 отсчётов s16le
SECOND = 32000  # байт звука в секунде (16 кГц, 16 бит, моно)


class FakeClock:
    """Подставные часы: время двигает только тест."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_hub(clock: FakeClock) -> DeviceHub:
    return DeviceHub(WINDOW_S, LATE_S, {"A": "Кухня"}, clock=clock)


async def eventually(condition: Callable[[], bool], timeout: float = 1.0) -> None:
    """Ждёт, пока условие станет истинным (таймер арбитра тикает раз в 50 мс)."""
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


async def connect(
    hub: DeviceHub, device_id: str | None, remote: str = "10.0.0.7:5000", protocol: int = 2
) -> tuple[FakeConnection, asyncio.Task[None]]:
    """Подключает поддельную колонку и шлёт hello (v2+ с device_id или v1 без него)."""
    conn = FakeConnection(remote)
    task = asyncio.create_task(hub.handle(conn))
    if device_id is None:
        conn.feed_json("hello", fw="1.0")
    else:
        conn.feed_json("hello", fw="2.0", device_id=device_id, protocol=protocol)
    await drop_volume(conn)
    return conn, task


async def drop_volume(conn: FakeConnection) -> None:
    """Хаб шлёт громкость сразу после hello — убираем этот кадр, чтобы тесты видели только своё."""
    for _ in range(100):
        frames = [m for m in conn.sent if isinstance(m, str) and '"volume"' in m]
        if frames:
            conn.sent.remove(frames[0])
            return
        await asyncio.sleep(0.002)


async def accepted_turn(
    hub: DeviceHub, clock: FakeClock, device_id: str, turn: int = 1, turn_id: int = 1, protocol: int = 2
) -> tuple[FakeConnection, asyncio.Task[None]]:
    """Подключает колонку, шлёт wake хода колонки turn и ждёт, пока хаб примет его.

    turn_id — ожидаемый номер хода в хабе: хаб выдаёт их по порядку принятия, с 1.
    """
    conn, task = await connect(hub, device_id, protocol=protocol)
    conn.feed_json("wake", turn=turn, level=-30.0)
    await asyncio.sleep(0.01)
    clock.now += WINDOW_S + 0.1
    await eventually(lambda: hub.is_active(device_id, turn_id))
    return conn, task


async def chunks(*parts: bytes) -> AsyncIterator[bytes]:
    """Поток звука ответа из готовых кусков."""
    for part in parts:
        yield part
