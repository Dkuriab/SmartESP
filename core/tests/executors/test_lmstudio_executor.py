"""Исполнитель LM Studio на подделке сервера: поток, ttl, рассуждение, прогрев, понятные ошибки."""

import json
from collections.abc import Callable

import httpx
import pytest

from smartesp.contracts import ChatMessage, ExecutorError, Reasoning, ReplyPart, ToolCall, ToolSpec
from smartesp.executors import LmStudioExecutor
from smartesp.executors.lmstudio_executor import ttl_seconds
from smartesp.executors.think_filter import ThinkFilter

MODEL = "qwen/qwen3-8b"
TOOL = ToolSpec("notes_list", "Список заметок", {"type": "object", "properties": {}})


def _sse(*chunks: dict[str, object]) -> bytes:
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}\n" for c in chunks]
    return ("\n".join([*lines, "data: [DONE]", ""])).encode()


def _delta(**delta: object) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


def _executor(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "http://localhost:1234",
    api_key: str = "",
    reasoning: Reasoning = "off",
    keep_alive: str = "24h",
) -> LmStudioExecutor:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LmStudioExecutor(
        MODEL, "Ты Кузя.", base_url, api_key, reasoning=reasoning, keep_alive=keep_alive, client=client
    )


async def _collect(executor: LmStudioExecutor, tools: tuple[ToolSpec, ...] = ()) -> list[ReplyPart]:
    return [p async for p in executor.run([ChatMessage("user", "Какие заметки?")], tools)]


async def test_streams_text_with_ttl_tools_and_no_key_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta(content="Привет"), _delta(content=", Аня!")))

    parts = await _collect(_executor(handler, base_url="http://mac.local:1234/v1/"), (TOOL,))
    assert [p.text for p in parts] == ["Привет", ", Аня!"]
    request = seen[0]
    assert str(request.url) == "http://mac.local:1234/v1/chat/completions"
    assert "Authorization" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == MODEL and body["stream"] is True and body["ttl"] == 86400
    assert body["tools"][0]["function"]["name"] == "notes_list"
    assert "reasoning_effort" not in body


async def test_key_and_reasoning_level_are_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta(content="Да.")))

    await _collect(_executor(handler, api_key="lm-key", reasoning="high", keep_alive="-1"))
    body = json.loads(seen[0].content)
    assert seen[0].headers["Authorization"] == "Bearer lm-key"
    assert body["reasoning_effort"] == "high" and "ttl" not in body


async def test_rejected_reasoning_is_retried_without_it() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if "reasoning_effort" in bodies[-1]:
            return httpx.Response(400, json={"error": "Unrecognized key: reasoning_effort"})
        return httpx.Response(200, content=_sse(_delta(content="Ок.")))

    assert [p.text for p in await _collect(_executor(handler, reasoning="low"))] == ["Ок."]
    assert ["reasoning_effort" in b for b in bodies] == [True, False]


async def test_think_blocks_and_reasoning_content_are_not_spoken() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        chunks = [
            _delta(reasoning_content="думаю…"),
            _delta(content="<thi"),
            _delta(content="nk>секрет</th"),
            _delta(content="ink>\n\nОтвет"),
            _delta(content=" готов."),
        ]
        return httpx.Response(200, content=_sse(*chunks))

    parts = await _collect(_executor(handler))
    assert "".join(p.text for p in parts) == "Ответ готов."


async def test_tool_calls_are_joined() -> None:
    call = {"index": 0, "id": "1", "type": "function", "function": {"name": "calc", "arguments": '{"a": 1}'}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(_delta(tool_calls=[call])))

    assert await _collect(_executor(handler), (TOOL,)) == [ReplyPart(tool_call=ToolCall("calc", {"a": 1}))]


@pytest.mark.parametrize(
    ("status", "error", "words"),
    [
        (404, {"error": {"message": f'Model "{MODEL}" not found'}}, f"В LM Studio нет модели «{MODEL}»"),
        (400, {"error": "No models loaded. Please load a model"}, "не загружена в LM Studio"),
        (400, {"error": {"message": "This model does not support tools"}}, "не умеет инструменты"),
        (401, {"error": "Invalid API key"}, "не принял ключ"),
        (500, {"error": "boom"}, "LM Studio ответил ошибкой 500"),
    ],
)
async def test_http_errors_are_plain_russian(status: int, error: dict[str, object], words: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=error)

    with pytest.raises(ExecutorError) as raised:
        await _collect(_executor(handler, api_key="lm-key"), (TOOL,))
    assert words in str(raised.value) and "lm-key" not in str(raised.value)


async def test_server_not_running_names_the_address() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    executor = _executor(offline, base_url="http://localhost:1234/")
    with pytest.raises(ExecutorError, match=r"Сервер LM Studio не запущен по адресу http://localhost:1234\b"):
        await _collect(executor)
    with pytest.raises(ExecutorError, match="не запущен"):
        await executor.warm_up()


async def test_warm_up_is_one_tiny_request() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "П"}}]})

    executor = _executor(handler, reasoning="high", keep_alive="30m")
    await executor.warm_up()
    assert len(seen) == 1
    body = seen[0]
    assert body["model"] == MODEL and body["max_tokens"] == 1 and body["stream"] is False
    assert body["ttl"] == 1800 and "tools" not in body and "reasoning_effort" not in body
    assert executor.models() == frozenset({f"@lmstudio/{MODEL}"})


async def test_warm_up_unknown_model_is_plain_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "model_not_found"}})

    with pytest.raises(ExecutorError, match="нет модели"):
        await _executor(handler).warm_up()


@pytest.mark.parametrize(
    ("keep_alive", "seconds"),
    [("24h", 86400), ("30m", 1800), ("90s", 90), ("1h30m", 5400), ("3600", 3600), ("-1", None), ("0", None)],
)
def test_ttl_from_keep_alive(keep_alive: str, seconds: int | None) -> None:
    assert ttl_seconds(keep_alive) == seconds
    assert ttl_seconds("всегда") is None


def test_think_filter_keeps_plain_text_and_drops_unclosed_think() -> None:
    plain = ThinkFilter()
    assert plain.feed("a < b, ") + plain.feed("<b>жирный</b>") + plain.end() == "a < b, <b>жирный</b>"
    unclosed = ThinkFilter()
    assert unclosed.feed("Начало <think>и рассуждение") + unclosed.end() == "Начало "


async def test_only_first_message_is_system() -> None:
    # шаблоны Qwen3.x в LM Studio падают на system не в начале («System message must be at the
    # beginning»): справка и пометки посреди диалога идут сообщением user с тем же текстом
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta(content="Да")))

    history = [
        ChatMessage("user", "Привет"),
        ChatMessage("assistant", "Привет!"),
        ChatMessage("system", "Справочные данные: колонка — Кухня."),
        ChatMessage("user", "Который час?"),
        ChatMessage("system", "Напоминание."),
    ]
    _ = [p async for p in _executor(handler).run(history)]
    messages = json.loads(seen[0].content)["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user", "user", "user"]
    assert messages[0]["content"] == "Ты Кузя."
    assert messages[3]["content"] == "Справочные данные: колонка — Кухня."
    assert messages[5]["content"] == "Напоминание."
