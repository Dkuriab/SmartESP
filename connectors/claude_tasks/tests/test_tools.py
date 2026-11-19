"""Инструменты через клиент-сессию SDK в памяти, с поддельным запуском Claude."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from claude_tasks_mcp.phrases import timeout_reason
from claude_tasks_mcp.server import build_server, main
from claude_tasks_mcp.settings import DEFAULT_TOOLS, Settings
from tests.conftest import FakeClock, FakeRunner, connect

Folders = tuple[tuple[str, Path], ...]
Make = Callable[..., MCPServer[Any]]


@pytest.fixture
def make(data_dir: Path, runner: FakeRunner, clock: FakeClock, folders: Folders) -> Make:
    """Фабрика сервера; каждый вызов — «новый запуск» с той же папкой данных."""

    def build(folders: Folders = folders, timeout_s: float = 1800) -> MCPServer[Any]:
        settings = Settings(folders=folders, tools=DEFAULT_TOOLS, timeout_s=timeout_s, claude_bin="")
        return build_server(settings, data_dir, runner=runner, now=clock)

    return build


async def test_tools_listed_with_russian_descriptions(make: Make) -> None:
    async with connect(make()) as s:
        tools = {t.name: t for t in (await s.client.list_tools()).tools}
    assert set(tools) == {"task_start", "task_status", "tasks", "task_result", "task_cancel"}
    assert "Клод" in (tools["task_start"].description or "")


async def test_start_runs_in_default_folder(make: Make, runner: FakeRunner, folders: Folders) -> None:
    async with connect(make()) as s:
        answer = await s.call("task_start", task="Почини тесты ядра, пожалуйста, очень нужно")
        assert answer == "Передала Клоду: «почини тесты ядра пожалуйста». Скажу, когда закончит."
        (call,) = await runner.started(1)
    assert call.prompt == "Почини тесты ядра, пожалуйста, очень нужно"
    assert call.folder == folders[0][1]


async def test_start_in_named_folder_and_subfolder(make: Make, runner: FakeRunner, folders: Folders) -> None:
    (folders[0][1] / "core").mkdir()
    async with connect(make()) as s:
        await s.call("task_start", task="раз", folder="Notes")
        await s.call("task_start", task="два", folder="smartesp/core")
        calls = await runner.started(2)
    assert [c.folder for c in calls] == [folders[1][1], folders[0][1] / "core"]


@pytest.mark.parametrize(
    ("folder", "expected"),
    [
        ("работа", "Нет папки «работа». Есть: smartesp, notes."),
        ("smartesp/../secret", "не из разрешённых"),
        ("/etc", "не из разрешённых"),
    ],
)
async def test_bad_folder_is_error(make: Make, runner: FakeRunner, folder: str, expected: str) -> None:
    async with connect(make()) as s:
        result = await s.client.call_tool("task_start", {"task": "x", "folder": folder})
    assert result.is_error
    assert expected in str(result.content[0])
    assert runner.calls == []


async def test_symlink_outside_is_error(
    make: Make, runner: FakeRunner, folders: Folders, tmp_path: Path
) -> None:
    (folders[0][1] / "out").symlink_to(tmp_path / "secret")
    async with connect(make()) as s:
        answer = await s.call("task_start", task="x", folder="smartesp/out")
    assert "не из разрешённых" in answer
    assert runner.calls == []


async def test_no_folders_configured(make: Make) -> None:
    async with connect(make(folders=())) as s:
        result = await s.client.call_tool("task_start", {"task": "x"})
    assert result.is_error
    assert "Не настроены папки для задач Клода" in str(result.content[0])


async def test_empty_task_is_error(make: Make) -> None:
    async with connect(make()) as s:
        result = await s.client.call_tool("task_start", {"task": "  "})
    assert result.is_error


async def test_done_announces_and_gives_result(make: Make, runner: FakeRunner, clock: FakeClock) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="почини тесты")
        await runner.started(1)
        clock.advance(125)
        assert await s.call("task_status") == "Задача «почини тесты» идёт 2 минуты."
        assert await s.call("task_result", name="почини") == "Клод ещё работает над «почини тесты»."
        clock.advance(60)
        runner.finish(0, True, "## Готово\nПочинила `test_x`. Причина — опечатка. Тесты зелёные. Ещё деталь.")
        assert await s.announce() == {
            "type": "announce",
            "text": "Клод закончил «почини тесты»: Готово.",
            "person": None,
        }
        assert await s.call("task_status", name="Почини тесты") == "Задача «почини тесты» готова за 3 минуты."
        assert await s.call("task_result", name="почини тесты") == (
            "Готово. Починила test_x. Причина — опечатка."
        )


async def test_failure_announces_reason(make: Make, runner: FakeRunner) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="обнови зависимости", person="гость")
        await runner.started(1)
        runner.finish(0, False, "не найдена программа claude")
        assert await s.announce() == {
            "type": "announce",
            "text": "Клод не справился с «обнови зависимости»: не найдена программа claude.",
            "person": "гость",
        }
        assert await s.call("task_status", person="гость") == (
            "Задача «обнови зависимости»: ошибка — не найдена программа claude."
        )
        assert await s.call("task_result", person="гость", name="обнови") == (
            "Клод не справился с «обнови зависимости»: не найдена программа claude."
        )


async def test_timeout_fails_task(make: Make, runner: FakeRunner) -> None:
    async with connect(make(timeout_s=0.05)) as s:
        await s.call("task_start", task="долгая задача")
        msg = await s.announce()
        assert msg["text"] == "Клод не справился с «долгая задача»: не уложился в отведённое время."
        assert runner.calls[0].cancelled


def test_timeout_text_in_minutes() -> None:
    assert timeout_reason(30 * 60) == "не уложился в 30 минут"
    assert timeout_reason(60) == "не уложился в 1 минуту"


async def test_cancel(make: Make, runner: FakeRunner) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="рефакторинг")
        await runner.started(1)
        assert await s.call("task_cancel", name="РЕФАКТОРИНГ") == "Задача «рефакторинг» отменена."
        assert runner.calls[0].cancelled
        assert await s.call("task_status") == "Задача «рефакторинг» отменена."
        assert await s.call("task_cancel", name="рефакторинг") == "Задача «рефакторинг» уже не идёт."
        assert s.pending() == []


async def test_limit_two_running(make: Make, runner: FakeRunner) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="первая")
        await s.call("task_start", task="вторая", person="гость")
        result = await s.client.call_tool("task_start", {"task": "третья"})
        assert result.is_error
        assert "Уже идут 2 задачи" in str(result.content[0])
        await runner.started(2)
        runner.finish(0, True, "Ок.")
        await s.announce()
        assert (await s.call("task_start", task="третья")).startswith("Передала Клоду: «третья»")


async def test_tasks_lists_last_five_and_names_repeat(make: Make, runner: FakeRunner) -> None:
    async with connect(make()) as s:
        assert await s.call("tasks") == "Задач для Клода ещё не было."
        for i in range(6):
            await s.call("task_start", task="задача")
            await runner.started(i + 1)
            runner.finish(i, True, "Ок.")
            await s.announce()
        await s.call("task_start", task="новая")
        listing = await s.call("tasks")
    assert listing == (
        "Задачи Клода: новая — идёт меньше минуты; задача 6 — готово; задача 5 — готово; "
        "задача 4 — готово; задача 3 — готово."
    )


async def test_unknown_and_ambiguous_names(make: Make, runner: FakeRunner) -> None:
    async with connect(make()) as s:
        assert "Задач для Клода ещё не было" in await s.call("task_status")
        await s.call("task_start", task="почини тесты")
        await s.call("task_start", task="почини сборку")
        assert await s.call("task_status", name="деплой") == "Задачи «деплой» нет."
        assert await s.call("task_result", name="почини") == "Уточни: «почини сборку», «почини тесты»."


async def test_people_are_separate(make: Make, runner: FakeRunner, data_dir: Path) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="гостевая", person="гость")
        assert await s.call("tasks") == "Задач для Клода ещё не было."
        assert (await s.call("tasks", person="гость")).startswith("Задачи Клода: гостевая")
        bad = await s.client.call_tool("tasks", {}, meta={"person": "../x"})
        assert bad.is_error
    assert (data_dir / "гость" / "tasks.json").exists()


async def test_journal_and_output_on_disk(make: Make, runner: FakeRunner, data_dir: Path) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="опиши проект")
        await runner.started(1)
        runner.finish(0, True, "Полный ответ Claude.\n\nС деталями.")
        await s.announce()
    outputs = list((data_dir / "home" / "output").iterdir())
    assert [p.read_text(encoding="utf-8") for p in outputs] == ["Полный ответ Claude.\n\nС деталями."]
    assert "опиши проект" in (data_dir / "home" / "tasks.json").read_text(encoding="utf-8")


async def test_restart_keeps_history_and_marks_interrupted(make: Make, runner: FakeRunner) -> None:
    async with connect(make()) as s:
        await s.call("task_start", task="готовая")
        await runner.started(1)
        runner.finish(0, True, "Сделано.")
        await s.announce()
        await s.call("task_start", task="брошенная")
        await runner.started(2)
    assert runner.calls[1].cancelled
    async with connect(make()) as s:
        assert await s.call("task_result", name="готовая") == "Сделано."
        assert await s.call("task_status", name="брошенная") == (
            "Задача «брошенная»: ошибка — прервана остановкой коннектора."
        )
        assert s.pending() == []


async def test_real_runner_with_fake_claude(
    data_dir: Path, folders: Folders, fake_bin: Path, tmp_path: Path
) -> None:
    """Сквозной путь с настоящим запуском подпроцесса — но поддельной программой `claude`."""
    settings = Settings(folders=folders, tools=DEFAULT_TOOLS, timeout_s=60, claude_bin=str(fake_bin))
    async with connect(build_server(settings, data_dir)) as s:
        await s.call("task_start", task="почини тест", folder="notes")
        assert (await s.announce())["text"] == "Клод закончил «почини тест»: Готово: поправила тест."
        assert await s.call("task_result") == "Готово: поправила тест. Подробности ниже."
    log = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert log["cwd"] == str(folders[1][1])
    assert log["prompt"] == "почини тест"


def test_main_without_data_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMARTESP_CONNECTOR_DATA", raising=False)
    with pytest.raises(SystemExit, match="SMARTESP_CONNECTOR_DATA"):
        main()
