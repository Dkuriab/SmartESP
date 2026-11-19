"""Инструменты через клиент-сессию SDK в памяти."""

from pathlib import Path

from mcp_types import RequestParamsMeta

from tests.conftest import ServerFactory, connect
from tests.fake_clock import FakeClock


async def test_tools_are_listed_with_russian_descriptions(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        tools = {t.name: t for t in (await s.client.list_tools()).tools}
    assert set(tools) == {"timer_start", "reminder_at", "timers", "timer_cancel"}
    assert "таймер" in (tools["timer_start"].description or "").lower()
    name_hint = tools["timer_start"].input_schema["properties"]["name"]["description"]
    assert "только если человек сам его назвал" in name_hint and "«[время] …»" in name_hint


async def test_timer_start_named(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        assert await s.call("timer_start", minutes=20, name="картошка") == "Таймер «картошка» на 20 минут."


async def test_timer_default_name_and_repeat(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        assert await s.call("timer_start", minutes=5) == "Таймер на 5 минут."
        assert await s.call("timer_start", minutes=1.5) == "Таймер «таймер 2» на 1 минуту 30 секунд."
        assert await s.call("timer_start", minutes=1, name="Картошка") == "Таймер «Картошка» на 1 минуту."
        assert await s.call("timer_start", minutes=1, name="картошка") == "Таймер «картошка 2» на 1 минуту."


async def test_timer_bad_minutes(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        result = await s.client.call_tool("timer_start", {"minutes": 0})
    assert result.is_error


async def test_list_timers_and_reminders(make_server: ServerFactory, clock: FakeClock) -> None:
    async with connect(make_server()) as s:
        assert await s.call("timers") == "Таймеров и напоминаний нет."
        await s.call("timer_start", minutes=20, name="картошка")
        assert (
            await s.call("reminder_at", time="18:30", text="позвонить маме")
            == "Напомню в 18:30: позвонить маме."
        )
        clock.advance(450)
        assert await s.call("timers") == (
            "картошка — 12 минут 30 секунд; напоминание «позвонить маме» — в 18:30."
        )


async def test_reminder_tomorrow(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        assert await s.call("reminder_at", time="07:00", text="зарядка") == "Напомню завтра в 07:00: зарядка."


async def test_reminder_bad_time_is_error(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        result = await s.client.call_tool("reminder_at", {"time": "когда-нибудь", "text": "x"})
    assert result.is_error
    assert "ЧЧ:ММ" in str(result.content[0])


async def test_cancel_by_name_case_insensitive(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", minutes=20, name="Картошка")
        assert await s.call("timer_cancel", name="картошка") == "Таймер «Картошка» отменён."
        assert await s.call("timers") == "Таймеров и напоминаний нет."
        assert await s.call("timer_cancel", name="чай") == "Таймера или напоминания «чай» нет."


async def test_cancel_reminder_and_all(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        await s.call("reminder_at", time="18:30", text="позвонить маме")
        assert await s.call("timer_cancel", name="Позвонить маме") == "Напоминание «позвонить маме» отменено."
        await s.call("timer_start", minutes=1)
        await s.call("timer_start", minutes=2)
        assert await s.call("timer_cancel", name="таймер") == "Таймер отменён."
        await s.call("timer_start", minutes=1)
        assert await s.call("timer_cancel", name="Все") == "Отменено: 2."
        assert await s.call("timer_cancel", name="все") == "Отменять нечего."


async def test_people_are_separate(make_server: ServerFactory, data_dir: Path) -> None:
    async with connect(make_server()) as s:
        await s.call("timer_start", person="гость", minutes=5, name="чай")
        assert await s.call("timers") == "Таймеров и напоминаний нет."
        assert await s.call("timers", person="гость") == "чай — 5 минут."
        await s.call("timer_start", minutes=5, name="чай")
        assert (
            await s.call("timer_start", person="гость", minutes=5, name="чай") == "Таймер «чай 2» на 5 минут."
        )
    assert (data_dir / "гость" / "timers.json").exists()
    assert (data_dir / "home" / "timers.json").exists()


async def test_bad_person_is_error(make_server: ServerFactory) -> None:
    async with connect(make_server()) as s:
        result = await s.client.call_tool("timers", {}, meta=RequestParamsMeta(person="../x"))
    assert result.is_error
