"""Выбор колонки, когда её не назвали, и проверка очереди."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from smartesp.contracts import DeviceInfo, StreamItem, StreamPhase, StreamRefused

from . import texts
from .sources import check_source

MAX_ITEMS = 1000


def check_items(items: Sequence[StreamItem], index: int) -> None:
    """Очередь не пуста, не длиннее MAX_ITEMS, index в ней, источники годятся; иначе StreamRefused."""
    if not items:
        raise StreamRefused("bad_source", texts.EMPTY)
    if len(items) > MAX_ITEMS:
        raise StreamRefused("bad_source", texts.TOO_MANY.format(limit=MAX_ITEMS))
    if not 0 <= index < len(items):
        raise StreamRefused("bad_source", texts.BAD_INDEX)
    for item in items:
        why = check_source(item.source)
        if why:
            raise StreamRefused("bad_source", why)


def pick_for_play(
    device_id: str | None, devices: list[DeviceInfo], supports: Callable[[str], bool], last: str | None
) -> str:
    """Колонка для новой очереди: названная; иначе колонка последнего разговора; иначе
    единственная, умеющая потоки."""
    if device_id:
        return device_id
    if last is not None:
        return last
    capable = [d.device_id for d in devices if d.connected and supports(d.device_id)]
    if len(capable) == 1:
        return capable[0]
    raise StreamRefused("no_device", texts.NO_DEVICE)


def pick_for_control(device_id: str | None, states: Mapping[str, StreamPhase], last: str | None) -> str:
    """Колонка для паузы, громкости и т. п.: названная; иначе единственная с потоком; иначе колонка
    последнего разговора, если поток на ней."""
    if device_id:
        return device_id
    active = [d for d, state in states.items() if state != "idle"]
    if len(active) == 1:
        return active[0]
    if last is not None and last in active:
        return last
    if not active:
        raise StreamRefused("not_playing", texts.NOT_PLAYING)
    raise StreamRefused("no_device", texts.SEVERAL)
