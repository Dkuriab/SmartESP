"""Проверка с настоящей моделью: правильно ли диспетчер (Gemma) выбирает, кому передать вопрос."""

import httpx
import ollama
import pytest

from smartesp.config.models import BIG_WHEN, DEFAULT_SYSTEM_PROMPT
from smartesp.contracts import ChatMessage, ToolCall
from smartesp.executors import OllamaExecutor
from smartesp.network import DELEGATE_TOOL, Target, delegate_rule, delegate_tool
from smartesp.stages.whisper_detect import PROMPT_HINT

MODEL = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive"
TARGETS = (
    Target(
        "big",
        "Большая модель",
        "сложные вопросы: рассуждения, расчёты, подробные объяснения, знания, которых может не быть у тебя",
    ),
    Target("coder", "Программист", "вопросы про программирование, код, ошибки в программах"),
)
# (ожидаемая цель или "" — отвечает сам, вопрос)
QUESTIONS = [
    ("", "Привет!"),
    ("", "Спасибо большое"),
    ("", "Как тебя зовут?"),
    ("big", "Почему пала Римская империя? Главные причины"),
    ("big", "Посчитай 17 процентов от 2384 и умножь на 3"),
    ("big", "Объясни подробно, как работает фотосинтез"),
    ("coder", "Как в питоне развернуть список?"),
    ("coder", "Напиши функцию сортировки пузырьком на C"),
]
MIN_RIGHT = 7


async def ask(executor: OllamaExecutor, question: str) -> tuple[str, str]:
    """Возвращает (выбранная цель или "", фраза до вызова/ответ)."""
    text = ""
    chosen = ""
    tools = [delegate_tool(TARGETS)]
    async for part in executor.run([ChatMessage("user", question)], tools):
        text += part.text
        if part.tool_call is not None and part.tool_call.name == DELEGATE_TOOL and not chosen:
            chosen = str(part.tool_call.arguments.get("executor", "?"))
    return chosen, text.strip()


@pytest.mark.models
async def test_gemma_routes_to_right_target() -> None:
    prompt = f"{DEFAULT_SYSTEM_PROMPT}\n{delegate_rule(TARGETS)}"
    executor = OllamaExecutor(MODEL, prompt, "5m")
    try:
        await executor.warm_up()
        await ollama.AsyncClient().show(MODEL)
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        pytest.skip("Ollama или модель недоступны")
    right = 0
    silent_calls: list[str] = []
    for want, question in QUESTIONS:
        got, text = await ask(executor, question)
        print(f"\nwant={want or 'self'} got={got or 'self'} q={question!r} phrase={text[:80]!r}")
        right += got == want
        if got and not text:
            silent_calls.append(question)
    print(f"right={right} of {len(QUESTIONS)}")
    assert right >= MIN_RIGHT
    assert not silent_calls, f"вызов без фразы: {silent_calls}"


DEFAULT_TARGET = (Target("big", "Большая модель", BIG_WHEN),)
DEFAULT_HARD = [
    "Почему пала Римская империя? Главные причины",
    "Объясни подробно, почему небо голубое",
    "Расскажи, как устроена иммунная система",
]
AFTER_HISTORY_HARD = [  # вопрос из истории (про небо) не повторяем: на повтор модель вправе ответить сама
    "Почему пала Римская империя? Главные причины",
    "Объясни подробно, как работает фотосинтез",
    "Расскажи, как устроена иммунная система",
]
DEFAULT_SIMPLE = ["Привет, как дела?", "Спасибо большое"]


@pytest.mark.models
async def test_gemma_default_config_one_target_with_whisper_hint() -> None:
    """Промпт как у ядра по умолчанию: одна цель big, подсказка про шёпот перед правилом."""
    prompt = f"{DEFAULT_SYSTEM_PROMPT}\n{PROMPT_HINT}\n{delegate_rule(DEFAULT_TARGET)}"
    executor = OllamaExecutor(MODEL, prompt, "5m")
    try:
        await executor.warm_up()
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        pytest.skip("Ollama или модель недоступны")
    tools = [delegate_tool(DEFAULT_TARGET)]

    async def delegated(question: str) -> bool:
        async for part in executor.run([ChatMessage("user", question)], tools):
            if part.tool_call is not None and part.tool_call.name == DELEGATE_TOOL:
                return True
        return False

    hard = [await delegated(q) for q in DEFAULT_HARD for _ in range(2)]
    simple = [await delegated(q) for q in DEFAULT_SIMPLE for _ in range(2)]
    print(f"\nhard delegated {sum(hard)} of {len(hard)}; simple delegated {sum(simple)} of {len(simple)}")
    assert sum(hard) >= 5
    assert not any(simple)


@pytest.mark.models
async def test_gemma_delegates_after_prior_delegated_turn_in_history() -> None:
    """В истории уже есть передача, записанная вызовом инструмента: следующий сложный вопрос снова уходит."""
    prompt = f"{DEFAULT_SYSTEM_PROMPT}\n{PROMPT_HINT}\n{delegate_rule(DEFAULT_TARGET)}"
    executor = OllamaExecutor(MODEL, prompt, "5m")
    try:
        await executor.warm_up()
    except (httpx.HTTPError, ConnectionError, ollama.ResponseError):
        pytest.skip("Ollama или модель недоступны")
    task = "Объяснить, почему небо голубое"
    history = [
        ChatMessage("user", "Объясни подробно, почему небо голубое"),
        ChatMessage(
            "assistant",
            "Минутку, сейчас узнаю.",
            tool_calls=(ToolCall(DELEGATE_TOOL, {"executor": "big", "task": task}),),
        ),
        ChatMessage(
            "tool",
            "Небо голубое из-за рассеяния солнечного света на молекулах воздуха.",
            tool_name=DELEGATE_TOOL,
        ),
    ]
    tools = [delegate_tool(DEFAULT_TARGET)]
    results: list[bool] = []
    for question in AFTER_HISTORY_HARD:
        for _ in range(2):
            messages = [*history, ChatMessage("user", question)]
            results.append(any([p.tool_call is not None async for p in executor.run(messages, tools)]))
    print(f"\ndelegated {sum(results)} of {len(results)} with delegated turn in history")
    assert sum(results) >= 5
