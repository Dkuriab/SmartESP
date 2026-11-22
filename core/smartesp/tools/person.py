"""Человек хода в вызовах инструментов: ящик, подставляющий `person` (→ `_meta.person`).

Сеть исполнителей вызывает инструменты без человека (`person=None`): она не знает ход.
Обёртка спрашивает человека у того, кто знает ход (связка передаёт
conversation.current_person), в момент вызова.
"""

from collections.abc import Callable

from smartesp.contracts import ToolBox, ToolResult, ToolSpec


class PersonalToolBox:
    """ToolBox поверх другого: вызов без человека получает человека текущего хода."""

    def __init__(self, inner: ToolBox, person: Callable[[], str | None]) -> None:
        """inner — настоящий ящик; person() — человек текущего хода (None — неизвестен)."""
        self._inner = inner
        self._person = person

    def specs(self) -> list[ToolSpec]:
        """Инструменты настоящего ящика."""
        return self._inner.specs()

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        """Вызов настоящего ящика; явный person главнее человека хода."""
        return await self._inner.call(name, arguments, person if person is not None else self._person())


def with_person(toolbox: ToolBox, person: Callable[[], str | None]) -> ToolBox:
    """Ящик, в вызовах которого человек текущего хода доходит до `_meta.person`."""
    return PersonalToolBox(toolbox, person)
