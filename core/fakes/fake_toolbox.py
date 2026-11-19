"""Подделка ToolBox: заданные инструменты и ответы, запоминает вызовы."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from smartesp.contracts import ToolResult, ToolSpec


def tool_spec(name: str, description: str = "") -> ToolSpec:
    """Описание инструмента без параметров (для тестов)."""
    return ToolSpec(name, description or f"Инструмент {name}", {"type": "object", "properties": {}})


class FakeToolBox:
    """Инструменты с готовыми ответами.

    results — ответ по имени инструмента; нет в results — «<имя>: готово».
    calls — вызовы по порядку: (имя, аргументы, person).
    """

    def __init__(
        self, specs: Sequence[ToolSpec] = (), results: Mapping[str, ToolResult] | None = None
    ) -> None:
        self.tools = list(specs)
        self.results = dict(results or {})
        self.calls: list[tuple[str, dict[str, object], str | None]] = []

    def specs(self) -> list[ToolSpec]:
        return list(self.tools)

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        self.calls.append((name, arguments, person))
        return self.results.get(name, ToolResult(f"{name}: готово"))
