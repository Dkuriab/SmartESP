"""Задачи «В работе» для ядра: идущие таймеры со сроком, срабатывание, отмена, перезапуск."""

from tests.conftest import START, ServerFactory, connect
from tests.fake_clock import FakeClock


async def test_timer_is_a_running_task_until_it_fires(make_server: ServerFactory, clock: FakeClock) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", person="Аня", minutes=20, name="картошка")
        (started,) = s.tasks
        assert started["type"] == "task" and started["status"] == "running"
        assert started["title"] == "Таймер «картошка»"
        assert started["person"] == "Аня"
        assert started["eta"] == "2026-11-19T14:20:00+03:00"
        clock.advance(20 * 60)
        await s.announce()
        assert [t["status"] for t in s.tasks] == ["running", "done"]
        assert s.tasks[1]["id"] == started["id"]


async def test_reminder_and_cancel(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        await s.call("reminder_at", time="18:30", text="позвонить маме")
        await s.call("timer_cancel", name="позвонить маме")
        assert [(t["title"], t["status"]) for t in s.tasks] == [
            ("Напоминание: позвонить маме", "running"),
            ("Напоминание: позвонить маме", "cancelled"),
        ]


async def test_running_timers_reported_again_after_restart(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=5)
        first = s.tasks[0]
    async with connect(make_server()) as s:
        await s.call("timers")  # подключение: отложенные уведомления уходят
        assert [(t["id"], t["status"], t["title"]) for t in s.tasks] == [(first["id"], "running", "Таймер")]
    assert first["eta"] == (START.replace(minute=5)).isoformat()
