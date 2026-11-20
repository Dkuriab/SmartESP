"""Тесты страховки честности: ложное «сделала» без инструмента, пустой ответ, вызов текстом."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

import pytest
from network_helpers import BIG, QUESTION, call

from fakes.fake_executor import FakeExecutor
from fakes.fake_toolbox import FakeToolBox, tool_spec
from smartesp.contracts import ChatMessage, Executor, ReplyPart, ToolCall, ToolResult, ToolSpec
from smartesp.network import ExecutorNetwork, Member
from smartesp.network.guard import EMPTY_PHRASE, NO_TOOL_PHRASE, NOT_HEARD_PHRASE, REMINDER

TIMER = tool_spec("timer_start")
LIGHT = [ChatMessage("user", "Включи свет на кухне")]


class Scripted:
    """Модель по сценарию: n-й вызов run отдаёт n-й ответ (после конца — последний)."""

    def __init__(self, *turns: Sequence[str | ReplyPart], gate: asyncio.Event | None = None) -> None:
        self.turns = turns
        self.calls: list[list[ChatMessage]] = []
        self.gate = gate  # после первого куска первого ответа ждём, пока не взведут

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        self.calls.append(messages)
        for index, part in enumerate(self.turns[min(len(self.calls), len(self.turns)) - 1]):
            if index == 1 and self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(0)
            yield part if isinstance(part, ReplyPart) else ReplyPart(part)


class SlowBox(FakeToolBox):
    """Ящик, чей инструмент отвечает, только когда взведут release."""

    def __init__(self) -> None:
        super().__init__([TIMER])
        self.release = asyncio.Event()

    async def call(self, name: str, arguments: dict[str, object], person: str | None) -> ToolResult:
        await self.release.wait()
        return await super().call(name, arguments, person)


def tool(name: str = "timer_start") -> ReplyPart:
    return ReplyPart(tool_call=ToolCall(name, {"seconds": 60}))


def net(entry: Executor, big: Executor | None = None, box: FakeToolBox | None = None) -> ExecutorNetwork:
    targets = (BIG,) if big is not None else ()
    members = {"dispatcher": Member(entry, "Диспетчер", targets, True, tools=(TIMER,))}
    if big is not None:
        members["big"] = Member(big, "Большая модель", (), True)
    return ExecutorNetwork("dispatcher", members, toolbox=box or FakeToolBox([TIMER]))


async def run(network: ExecutorNetwork, messages: list[ChatMessage] = LIGHT) -> list[ReplyPart]:
    return [p async for p in network.run(messages)]


def said(parts: list[ReplyPart]) -> str:
    return "".join(p.text for p in parts)


def guards(parts: list[ReplyPart]) -> list[str]:
    return [p.guard for p in parts if p.guard]


async def test_false_claim_is_retried_with_reminder_and_never_spoken(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    model = Scripted(["Свет на кухне включён."], ["У меня нет доступа к освещению."])
    parts = await run(net(model))
    assert said(parts) == "У меня нет доступа к освещению."
    assert guards(parts) == ["retried"]
    retry = model.calls[1]
    assert retry[: len(LIGHT)] == LIGHT
    assert retry[len(LIGHT) :] == [ChatMessage("system", REMINDER)]  # ложь в диалог не попадает
    assert any("повторный прогон" in r.getMessage() and r.levelno == logging.INFO for r in caplog.records)


async def test_claim_twice_becomes_honest_fallback() -> None:
    model = Scripted(["Включаю музыку."], ["Понял, включаю музыку."])
    parts = await run(net(model))
    assert said(parts) == NO_TOOL_PHRASE
    assert guards(parts)[-1] == "fallback"
    assert len(model.calls) == 2  # повторный прогон только один


async def test_retry_may_call_the_tool() -> None:
    box = FakeToolBox([TIMER])
    model = Scripted(["Поставила таймер на одну минуту."], [tool()], ["Таймер на минуту запущен."])
    parts = await run(net(model, box=box), [ChatMessage("user", "Поставь таймер на минуту")])
    assert said(parts) == "Таймер на минуту запущен."
    assert [c[0] for c in box.calls] == ["timer_start"]
    assert guards(parts) == ["retried"]


async def test_claim_before_a_real_call_is_not_a_violation() -> None:
    box = FakeToolBox([TIMER])
    model = Scripted(["Ставлю таймер на одну минуту.\n", tool()], ["Готово, таймер идёт."])
    parts = await run(net(model, box=box))
    assert said(parts).replace("\n", "") == "Ставлю таймер на одну минуту.Готово, таймер идёт."
    assert guards(parts) == [] and len(model.calls) == 2  # второй прогон — продолжение после инструмента


async def test_held_claim_is_released_when_tool_starts_not_when_it_ends() -> None:
    box = SlowBox()
    model = Scripted(["Ставлю таймер на одну минуту.\n", tool()], ["Готово."])
    stream = net(model, box=box).run(LIGHT)
    first = await asyncio.wait_for(anext(stream), 1)
    assert first.text == "Ставлю таймер на одну минуту.\n"  # инструмент ещё не ответил
    box.release.set()
    rest = [p async for p in stream]
    assert "Готово." in said(rest)


async def test_delegate_after_claim_phrase_is_not_a_violation() -> None:
    model = Scripted(["Сейчас включу ответ большой модели. ", call(task="Свет")])
    big = Scripted(["Нет доступа к освещению."])
    parts = await run(net(model, big))
    assert [p.handoff.target for p in parts if p.handoff] == ["big"]
    assert len(model.calls) == 1 and guards(parts) == []


async def test_empty_answer_is_retried_then_fallback() -> None:
    model = Scripted([], [""])
    parts = await run(net(model), [ChatMessage("user", "Поставь таймер")])
    assert said(parts) == NO_TOOL_PHRASE
    assert len(model.calls) == 2
    assert model.calls[1][-1] == ChatMessage("system", REMINDER)


async def test_empty_answer_to_empty_question_asks_to_repeat() -> None:
    parts = await run(net(Scripted([])), [ChatMessage("user", "")])
    assert said(parts) == NOT_HEARD_PHRASE


async def test_empty_answer_after_tool_call_is_left_alone() -> None:
    box = FakeToolBox([TIMER])
    model = Scripted([tool()], [])
    parts = await run(net(model, box=box))
    assert said(parts) == "" and guards(parts) == []
    assert len(box.calls) == 1  # инструмент не вызван второй раз


async def test_tool_call_spelled_as_json_is_retried() -> None:
    spelled = '{ "name": "delegate", "arguments": {"executor": "big", "task": "Рим"} }'
    model = Scripted([spelled], [call(task="Рим")])
    big = Scripted(["Рим пал в 476 году."])
    parts = await run(net(model, big), [ChatMessage("user", "Почему пал Рим?")])
    assert "name" not in said(parts)
    handoff = next(p for p in parts if p.handoff)
    assert handoff.guard == "retried"  # метка доходит и до хода, начатого передачей


@pytest.mark.parametrize(
    "answer",
    [
        "Я записала бы, но у меня нет такого инструмента.",
        "Не могу включить свет — нет доступа.",
        "Небо голубое, потому что воздух сильнее рассеивает синий свет.",
    ],
)
async def test_honest_answers_are_not_retried(answer: str) -> None:
    model = Scripted([answer])
    parts = await run(net(model))
    assert said(parts) == answer and guards(parts) == [] and len(model.calls) == 1


async def test_normal_answer_flows_after_first_sentence_without_waiting_for_the_end() -> None:
    gate = asyncio.Event()
    model = Scripted(["Небо голубое из-за рассеяния света. ", "Синий рассеивается сильнее."], gate=gate)
    stream = net(model).run(QUESTION)
    first = await asyncio.wait_for(anext(stream), 1)  # модель ещё не досказала
    assert first.text == "Небо голубое из-за рассеяния света. "
    gate.set()
    assert said([p async for p in stream]) == "Синий рассеивается сильнее."


async def test_target_answers_are_not_checked() -> None:
    model = Scripted([call(task="Включи свет")])
    big = Scripted(["Свет на кухне включён."])
    parts = await run(net(model, big))
    assert "Свет на кухне включён." in said(parts) and len(big.calls) == 1


async def test_fact_with_participle_on_a_question_is_not_retried() -> None:
    answer = "Первый спутник был запущен 4 октября 1957 года."
    model = Scripted([answer])
    parts = await run(net(model), [ChatMessage("user", "Когда запустили первый спутник?")])
    assert said(parts) == answer and len(model.calls) == 1


async def test_empty_answer_to_a_chat_question_gets_neutral_phrase() -> None:
    parts = await run(net(Scripted([], [])), [ChatMessage("user", "Спасибо!")])
    assert said(parts) == EMPTY_PHRASE and guards(parts) == ["fallback"]


async def test_confirmation_after_a_tool_turn_is_not_retried() -> None:
    history = [
        ChatMessage("user", "Поставь таймер на десять минут"),
        ChatMessage("assistant", "", tool_calls=(ToolCall("timer_start", {"seconds": 600}),)),
        ChatMessage("tool", "Таймер на 10 минут", tool_name="timer_start"),
        ChatMessage("assistant", "Таймер на десять минут."),
        ChatMessage("user", "Поставь таймер на десять минут"),
    ]
    model = Scripted(["Таймер уже поставлен на десять минут."])
    parts = await run(net(model), history)
    assert said(parts) == "Таймер уже поставлен на десять минут." and len(model.calls) == 1


async def test_style_tag_answer_flows_like_any_other() -> None:
    gate = asyncio.Event()
    model = Scripted(["[style:quiet] Небо голубое из-за рассеяния. ", "Ещё."], gate=gate)
    stream = net(model).run(QUESTION)
    first = await asyncio.wait_for(anext(stream), 1)  # не держится до конца как «JSON»
    assert first.text.startswith("[style:quiet]")
    gate.set()
    await stream.aclose()  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]


async def test_closing_while_a_claim_is_held_closes_the_model() -> None:
    model = FakeExecutor(["Включаю музыку прямо сейчас. ", "А теперь громче."], delay=10)
    stream = net(model).run(LIGHT)
    reading = asyncio.ensure_future(anext(stream))
    await asyncio.sleep(0.05)  # чтение модели идёт в отдельной задаче страховки
    assert not reading.done()
    reading.cancel()  # перебили, пока страховка ждёт кусок
    await asyncio.gather(reading, return_exceptions=True)
    await stream.aclose()  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    assert model.closed_early


async def test_caller_tool_counts_as_a_call() -> None:
    caller = tool_spec("reply_photo")
    model = Scripted(["Включаю камеру прямо сейчас. ", ReplyPart(tool_call=ToolCall("reply_photo", {}))])
    network = net(model)
    parts = [p async for p in network.run(LIGHT, [caller])]
    assert [p.tool_call.name for p in parts if p.tool_call] == ["reply_photo"]
    assert said(parts) == "Включаю камеру прямо сейчас. " and len(model.calls) == 1


async def test_false_claim_after_a_clarification_is_caught() -> None:
    history = [
        ChatMessage("user", "Запиши обед: гречка 150 грамм"),
        ChatMessage("assistant", "", tool_calls=(ToolCall("food_log", {"text": "гречка 150"}),)),
        ChatMessage("tool", "Уточни: гречка сухая или варёная?", tool_name="food_log"),
        ChatMessage("assistant", "Уточни: гречка сухая или варёная?"),
        ChatMessage("user", "Варёная"),
    ]
    model = Scripted(["Записала гречку на обед."], ["Не получилось записать: нужен инструмент питания."])
    parts = await run(net(model), history)
    assert guards(parts) == ["retried"] and len(model.calls) == 2
