"""Живая подсветка хода: кто из исполнителей сейчас работает и какие инструменты вызываются.

События для интерфейса:
- executor_active {turn_id, device_id, executor, state}: state — thinking (ждём первый
  текст), speaking (его ответ звучит), done (закончил или передал задачу);
- tool_call {turn_id, device_id, executor, connector, tool, state, ok}: state — started
  или finished; законченные вызовы копятся в turn.tools (для turn_finished) и в
  turn.exchanges (с аргументами и ответом инструмента — для истории).

Ход привязывается к контексту своей задачи (contextvars): наблюдатель вызовов, который
сеть исполнителей получила при сборке (tool_observer), узнаёт ход без явной передачи.
Задачи, созданные из хода (ожидание запоздавшего ответа), получают копию контекста.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar

from smartesp.contracts import ReplyPart, ToolCall, ToolObserver, ToolUse

from .streams import closing
from .turn import ToolExchange, Turn, turn_id

_log = logging.getLogger(__name__)

THINKING = "thinking"
SPEAKING = "speaking"
DONE = "done"

Publish = Callable[[str, dict[str, object]], None]

_current: ContextVar[TurnActivity | None] = ContextVar("smartesp_turn_activity", default=None)


MAX_RESULT = 4000  # символов ответа скилла в ленте: длинные страницы не раздувают историю ходов


def _short(text: str) -> str:
    """Ответ скилла для ленты: длинный — обрезан с пометкой."""
    return text if len(text) <= MAX_RESULT else f"{text[:MAX_RESULT]}… (ещё {len(text) - MAX_RESULT} симв.)"


class TurnActivity:
    """Подсветка одного хода: состояние текущего исполнителя и вызовы инструментов."""

    def __init__(self, turn: Turn, publish: Publish) -> None:
        """turn — ход; publish(kind, data) — куда публиковать события."""
        self._turn = turn
        self._publish = publish
        self._executor = ""
        self._state = DONE

    @classmethod
    def bind(cls, turn: Turn, publish: Publish) -> TurnActivity:
        """Создаёт подсветку хода и привязывает её к контексту текущей задачи (задачи хода)."""
        activity = cls(turn, publish)
        _current.set(activity)
        return activity

    async def watch(self, parts: AsyncIterator[ReplyPart]) -> AsyncIterator[ReplyPart]:
        """Отдаёт куски исполнителя как есть, отмечая, кто думает, говорит и кому передана задача.

        Входной исполнитель — первый в пути хода. Поток отложенного ответа (turn.deferred)
        отмечает конец цели сам, когда его закроют.
        """
        self._set(self._turn.path[0] if self._turn.path else "", THINKING)
        try:
            async with closing(parts):
                async for part in parts:
                    self._see(part)
                    yield part
        finally:
            if self._turn.deferred:
                self._done()

    @property
    def person(self) -> str:
        """Человек хода ("" — неизвестен)."""
        return self._turn.person

    def finish(self) -> None:
        """Ход закончен: текущий исполнитель — done (если ответ не отложен: тот закончит сам)."""
        if not self._turn.deferred:
            self._done()

    def tool(self, use: ToolUse, connector: str) -> None:
        """Событие tool_call; законченный вызов — в turn.tools и (с аргументами и ответом) в exchanges."""
        self._publish(
            "tool_call",
            {
                **self._ids(),
                "executor": use.executor,
                "connector": connector,
                "tool": use.tool,
                "state": use.state,
                "ok": use.ok,
            },
        )
        if use.state == "finished":
            self._turn.tools.append(
                {
                    "executor": use.executor,
                    "connector": connector,
                    "tool": use.tool,
                    "ok": use.ok,
                    "arguments": dict(use.arguments),  # что спросили у скилла — видно в ленте
                    "result": _short(use.result),  # что он ответил (длинное — обрезано)
                }
            )
            call = ToolCall(use.tool, dict(use.arguments))
            self._turn.exchanges.append(ToolExchange(use.executor, call, use.result))

    def _see(self, part: ReplyPart) -> None:
        if part.handoff is not None:
            self._done()
            self._set(part.handoff.target, THINKING)
        elif part.text.strip() and self._state == THINKING:
            self._set(self._executor, SPEAKING)

    def _done(self) -> None:
        if self._executor and self._state != DONE:
            self._set(self._executor, DONE)

    def _set(self, executor: str, state: str) -> None:
        self._executor, self._state = executor, state
        if executor:
            self._publish("executor_active", {**self._ids(), "executor": executor, "state": state})

    def _ids(self) -> dict[str, object]:
        return {"turn_id": turn_id(self._turn), "device_id": self._turn.utterance.device_id}


def current_person() -> str | None:
    """Человек хода текущей задачи (узнан по голосу или назван каналом API); вне хода или не узнан — None.

    Читается в момент вызова: человек, узнанный после начала хода, тоже виден.
    """
    activity = _current.get()
    return (activity.person or None) if activity is not None else None


def watched(parts: AsyncIterator[ReplyPart]) -> AsyncIterator[ReplyPart]:
    """Куски исполнителя под подсветкой хода текущей задачи; вне хода — как есть."""
    activity = _current.get()
    return parts if activity is None else activity.watch(parts)


def tool_observer(connector_of: Callable[[str], str]) -> ToolObserver:
    """Наблюдатель вызовов инструментов для сети исполнителей: события хода, в котором идёт вызов.

    connector_of(имя инструмента) — id его коннектора ("" — неизвестен). Вызов вне хода — без событий.
    """

    def observe(use: ToolUse) -> None:
        activity = _current.get()
        if activity is None:
            return
        try:
            activity.tool(use, connector_of(use.tool))
        except Exception:  # noqa: BLE001 — подсветка вторична, ход важнее
            _log.exception("Событие вызова инструмента не опубликовано")

    return observe
