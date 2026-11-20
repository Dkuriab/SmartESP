"""Подделка реестра «В работе»: запоминает сообщения, отдаёт заданный список."""

from __future__ import annotations

from smartesp.contracts import TaskInfo, TaskReport


class FakeTaskBoard:
    def __init__(self) -> None:
        self.reports: list[TaskReport] = []
        self.forgotten: list[str] = []
        self.items: list[TaskInfo] = []  # что вернёт tasks()

    def report(self, report: TaskReport) -> None:
        self.reports.append(report)

    def forget(self, source: str) -> None:
        self.forgotten.append(source)

    def tasks(self) -> list[TaskInfo]:
        return list(self.items)
