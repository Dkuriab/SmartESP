"""Срабатывание: объявление в клиентскую сессию, перезапуск, пропущенные, отмена."""

import json
import threading
from pathlib import Path
from typing import Any

import anyio
import pytest

from tests.conftest import ServerFactory, connect
from tests.fake_clock import FakeClock
from timers_mcp.board import Board
from timers_mcp.store import Store


async def test_timer_fires_announce(make_server: ServerFactory, clock: FakeClock) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=20, name="картошка")
        clock.advance(20 * 60)
        msg = await s.announce()
        assert msg == {"type": "announce", "text": "Таймер «картошка»: время вышло.", "person": None}
        assert await s.call("timers") == "Таймеров и напоминаний нет."


async def test_default_timer_and_reminder_fire_with_person(
    make_server: ServerFactory, clock: FakeClock
) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", person="гость", minutes=1)
        await s.call("reminder_at", person="гость", time="14:02", text="выключить плиту")
        clock.advance(60)
        assert await s.announce() == {"type": "announce", "text": "Таймер: время вышло.", "person": "гость"}
        clock.advance(60)
        assert await s.announce() == {
            "type": "announce",
            "text": "Напоминание: выключить плиту.",
            "person": "гость",
        }


async def test_cancelled_timer_does_not_fire(make_server: ServerFactory, clock: FakeClock) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=1, name="чай")
        await s.call("timer_start", minutes=2, name="суп")
        await s.call("timer_cancel", name="чай")
        clock.advance(60)
        clock.advance(60)
        assert (await s.announce())["text"] == "Таймер «суп»: время вышло."
        assert s.pending() == []


async def test_state_survives_restart(make_server: ServerFactory, clock: FakeClock, data_dir: Path) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=20, name="картошка")
    saved = json.loads((data_dir / "home" / "timers.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["name"] == "картошка"
    clock.advance(5 * 60)
    async with connect(make_server()) as s:
        assert await s.call("timers") == "картошка — 15 минут."
        clock.advance(15 * 60)
        assert (await s.announce())["text"] == "Таймер «картошка»: время вышло."


async def test_missed_while_down_announced_once(make_server: ServerFactory, clock: FakeClock) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=20, name="картошка")
        await s.call("reminder_at", person="гость", time="14:30", text="позвонить маме")
    clock.advance(3600)
    async with connect(make_server()) as s:
        got = {(await s.announce())["text"], (await s.announce())["text"]}
        assert got == {
            "Пропущен таймер «картошка» (сработал в 14:20).",
            "Пропущено напоминание «позвонить маме» (сработало в 14:30).",
        }
        assert await s.call("timers") == "Таймеров и напоминаний нет."
        assert s.pending() == []
    async with connect(make_server()) as s:
        await s.call("timers")
        assert s.pending() == []


async def test_concurrent_starts_get_distinct_names(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        answers: list[str] = []

        async def start() -> None:
            answers.append(await s.call("timer_start", minutes=5))

        async with anyio.create_task_group() as tg:
            for _ in range(20):
                tg.start_soon(start)
        assert len(set(answers)) == 20
        assert (await s.call("timers")).count("таймер") == 20


async def test_tools_touch_board_on_event_loop_thread(
    make_server: ServerFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Доска меняется только из цикла событий — там же, где срабатывания (иначе гонка)."""
    threads: set[int] = set()
    for method in ("start_timer", "add_reminder", "active", "cancel"):
        original = getattr(Board, method)

        def spy(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
            threads.add(threading.get_ident())
            return _original(*args, **kwargs)

        monkeypatch.setattr(Board, method, spy)
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=5)
        await s.call("reminder_at", time="18:30", text="чай")
        await s.call("timers")
        await s.call("timer_cancel", name="все")
    assert threads == {threading.get_ident()}


async def test_start_while_another_fires_is_kept(
    make_server: ServerFactory, clock: FakeClock, data_dir: Path
) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=1, name="чай")
        for i in range(20):
            clock.advance(60)
            await s.call("timer_start", minutes=1, name=f"суп {i}")
            await s.announce()
        saved = json.loads((data_dir / "home" / "timers.json").read_text(encoding="utf-8"))
        assert [item["name"] for item in saved["items"]] == ["суп 19"]
        assert await s.call("timers") == "суп 19 — 1 минута."


async def test_firing_survives_write_error(
    make_server: ServerFactory, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=1, name="чай")
        await s.call("timer_start", minutes=2, name="суп")
        original = Store.save

        def broken(*args: Any, **kwargs: Any) -> None:
            monkeypatch.setattr(Store, "save", original)
            raise OSError("диск заполнен")

        monkeypatch.setattr(Store, "save", broken)
        clock.advance(60)
        assert (await s.announce())["text"] == "Таймер «чай»: время вышло."
        clock.advance(60)
        assert (await s.announce())["text"] == "Таймер «суп»: время вышло."
