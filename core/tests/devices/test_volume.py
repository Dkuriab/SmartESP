"""Громкость колонок: из настроек — колонке при подключении и при правке; видна в сведениях."""

import asyncio

from hub_helpers import FakeClock, eventually, make_hub

from fakes.fake_connection import FakeConnection


def volumes(conn: FakeConnection) -> list[str]:
    return [m for m in conn.sent if isinstance(m, str) and '"volume"' in m]


async def test_volume_on_connect_and_on_change_only_for_changed() -> None:
    hub = make_hub(FakeClock())
    hub.set_volumes({"A": 70})
    a, b = FakeConnection(), FakeConnection()
    tasks = [asyncio.create_task(hub.handle(a)), asyncio.create_task(hub.handle(b))]
    a.feed_json("hello", fw="0.6", device_id="A", protocol=4)
    b.feed_json("hello", fw="0.6", device_id="B", protocol=4)
    await eventually(lambda: bool(volumes(a)) and bool(volumes(b)))
    assert volumes(a) == ['{"type":"volume","value":0.7}']
    assert volumes(b) == ['{"type":"volume","value":0.5}']  # не задана — как у прошивки
    hub.set_volumes({"A": 70, "B": 20})
    await eventually(lambda: len(volumes(b)) == 2)
    assert volumes(b)[-1] == '{"type":"volume","value":0.2}' and len(volumes(a)) == 1  # у A не менялась
    info = {d.device_id: d.volume for d in hub.devices()}
    assert info == {"A": 70, "B": 20}
    for task in tasks:
        task.cancel()
