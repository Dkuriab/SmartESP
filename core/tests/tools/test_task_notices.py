"""Задачи коннекторов «В работе»: разбор уведомления, путь до реестра, отмена при падении."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import types
from mcp_hub_helpers import spec, wait_until

from smartesp.contracts import TaskInfo, TaskReport
from smartesp.tools import McpHub
from smartesp.tools.messages import handle_log


class Board:
    def __init__(self) -> None:
        self.reports: list[TaskReport] = []
        self.forgotten: list[str] = []

    def report(self, report: TaskReport) -> None:
        self.reports.append(report)

    def forget(self, source: str) -> None:
        self.forgotten.append(source)

    def tasks(self) -> list[TaskInfo]:
        return []


def note(data: object, logger: str = "smartesp") -> types.LoggingMessageNotificationParams:
    return types.LoggingMessageNotificationParams(level="info", logger=logger, data=data)


def test_task_notice_goes_to_board() -> None:
    board = Board()
    data = {
        "type": "task",
        "id": "t1",
        "title": "Картошка",
        "eta": "2026-11-20T18:30:00+00:00",
        "person": "Аня",
    }
    handle_log(note(data), "timers", None, board)
    (report,) = board.reports
    assert (report.source, report.id, report.title, report.status) == (
        "connector:timers",
        "t1",
        "Картошка",
        "running",
    )
    assert report.eta == datetime(2026, 11, 20, 18, 30, tzinfo=UTC).timestamp()
    assert report.person == "Аня"


def test_task_notice_with_number_eta_and_result() -> None:
    board = Board()
    handle_log(
        note({"type": "task", "id": 7, "status": "done", "eta": 1700000000, "result": "ок"}), "c", None, board
    )
    (report,) = board.reports
    assert (report.id, report.status, report.eta, report.result) == ("7", "done", 1700000000.0, "ок")


@pytest.mark.parametrize(
    "data",
    [
        {"type": "task", "title": "без id"},
        {"type": "task", "id": "a", "status": "спит"},
        {"type": "task", "id": "a", "eta": "завтра"},
        {"type": "task", "id": "a", "title": 5},
        {"type": "task", "id": True},
    ],
)
def test_bad_task_notice_is_logged_not_reported(
    data: dict[str, object], caplog: pytest.LogCaptureFixture
) -> None:
    board = Board()
    with caplog.at_level(logging.WARNING, logger="smartesp.tools"):
        handle_log(note(data), "c", None, board)
    assert board.reports == []
    assert "неверная задача" in caplog.text


def test_task_from_other_logger_is_plain_log() -> None:
    board = Board()
    handle_log(note({"type": "task", "id": "a", "title": "x"}, logger="other"), "c", None, board)
    assert board.reports == []


def test_failing_board_does_not_raise() -> None:
    class Broken(Board):
        def report(self, report: TaskReport) -> None:
            raise RuntimeError("сломался")

    handle_log(note({"type": "task", "id": "a", "title": "x"}), "c", None, Broken())


async def test_task_reaches_board_and_crash_forgets_tasks(tmp_path: Path) -> None:
    board = Board()
    hub = McpHub(tmp_path, tasks=board, restart_delays_s=(30.0,))
    try:
        await hub.start([spec("a")])
        await hub.call("task", {"task_id": "x", "title": "Сводка", "status": "running"}, None)
        await wait_until(lambda: len(board.reports) == 1)
        assert board.reports[0].source == "connector:a"
        assert board.forgotten == []
        await hub.call("crash", {}, None)
        await wait_until(lambda: board.forgotten == ["connector:a"])
    finally:
        await hub.aclose()
