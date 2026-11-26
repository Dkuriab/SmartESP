"""Проверка с настоящей моделью: факты диспетчер ищет инструментом, а не передаёт и не выдумывает."""

import pytest

from smartesp.config.models import BIG_WHEN, DEFAULT_SYSTEM_PROMPT
from smartesp.contracts import ChatMessage, ExecutorError, ToolSpec
from smartesp.executors import OllamaExecutor
from smartesp.network import DELEGATE_TOOL, Target, delegate_rule, delegate_tool
from smartesp.network.rules import TOOLS_RULE

MODEL = "gpt-oss:20b"  # диспетчер по умолчанию
TARGETS = (Target("big", "Большая модель", BIG_WHEN),)
WEB = ToolSpec(  # описание — как у коннектора web
    "web_search",
    "Поиск в интернете (DuckDuckGo). Вызывайте для свежих фактов, новостей, цен, курсов, "
    "расписаний и всего, чего вы не знаете наверняка. query — запрос, как в поисковике: "
    "«курс доллара сегодня». Отвечайте коротко своими словами и называйте сайт-источник "
    "(домен), адреса вслух не читайте.",
    {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
)
TIMER = ToolSpec(
    "timer_set",
    "Поставить таймер. seconds — длительность.",
    {"type": "object", "properties": {"seconds": {"type": "integer"}}, "required": ["seconds"]},
)
FACTS = [
    "Кто сейчас премьер-министр Великобритании?",
    "Какое население Казани?",
    "Какой робот-пылесос лучше купить до тридцати тысяч?",
    "Как настроить гостевую сеть на роутере Кинетик?",
    "Что нового в последней версии айОС?",
    "Чем отличается Оземпик от Мунджаро?",
    "Почему в этом году подорожал кофе?",
    "Сколько калорий в ста граммах варёной гречки?",
    "Чем закончился последний сезон Очень странных дел?",
    "Какие сейчас лучшие беспроводные наушники с шумоподавлением?",
]
SIMPLE = ["Привет, как дела?", "Расскажи короткую шутку"]
MIN_SEARCHED = 18  # из 20; замер 2026-11-26: 20 из 20 (до правила — 13, 6 ушли большой модели)


async def where(executor: OllamaExecutor, question: str) -> str:
    """Первый вызванный инструмент (delegate — "big") или "self", если модель ответила сама."""
    tools = [delegate_tool(TARGETS), WEB, TIMER]
    async for part in executor.run([ChatMessage("user", question)], tools):
        if part.tool_call is not None:
            return "big" if part.tool_call.name == DELEGATE_TOOL else part.tool_call.name
    return "self"


@pytest.mark.models
async def test_facts_go_to_search_not_to_big_model() -> None:
    prompt = "\n".join([DEFAULT_SYSTEM_PROMPT, delegate_rule(TARGETS), TOOLS_RULE])
    executor = OllamaExecutor(MODEL, prompt, "5m", reasoning="low")
    try:
        await executor.warm_up()
    except ExecutorError:
        pytest.skip("Ollama или модель недоступны")
    facts = [await where(executor, q) for q in FACTS for _ in range(2)]
    simple = [await where(executor, q) for q in SIMPLE for _ in range(2)]
    print(f"\nfacts: {facts}\nsimple: {simple}")
    assert facts.count("web_search") >= MIN_SEARCHED
    assert simple == ["self"] * len(simple)
