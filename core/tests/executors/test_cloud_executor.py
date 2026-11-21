"""Облачный исполнитель: поток SSE, вызовы инструментов, ошибки сервиса понятным текстом."""

import json
from collections.abc import Callable

import httpx
import pytest

from smartesp.contracts import ChatMessage, ExecutorError, Reasoning, ReplyPart, ToolCall, ToolSpec
from smartesp.executors import CloudExecutor
from smartesp.executors.cloud_executor import messages_payload

KEY = "sk-or-test-key"
TOOL = ToolSpec("notes_list", "Список заметок", {"type": "object", "properties": {}})


def _sse(*chunks: dict[str, object]) -> bytes:
    lines = [": OPENROUTER PROCESSING", ""]
    lines += [f"data: {json.dumps(c, ensure_ascii=False)}\n" for c in chunks]
    return ("\n".join([*lines, "data: [DONE]", ""])).encode()


def _delta(**delta: object) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


def _executor(
    handler: Callable[[httpx.Request], httpx.Response],
    reasoning: Reasoning = "off",
    service: str = "OpenRouter",
) -> CloudExecutor:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    url = "https://cloud.test/api/v1/"
    return CloudExecutor(
        "google/gemini-2.5-flash", "Ты Кузя.", url, KEY, client=client, reasoning=reasoning, service=service
    )


async def _collect(executor: CloudExecutor, tools: tuple[ToolSpec, ...] = ()) -> list[ReplyPart]:
    return [p async for p in executor.run([ChatMessage("user", "Какие заметки?")], tools)]


async def test_streams_text_and_sends_model_tools_reasoning_and_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_sse(_delta(content="Привет"), _delta(content=", Аня!")))

    parts = await _collect(_executor(handler, reasoning="low"), (TOOL,))
    assert [p.text for p in parts] == ["Привет", ", Аня!"]
    request = seen[0]
    assert str(request.url) == "https://cloud.test/api/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "google/gemini-2.5-flash" and body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "Ты Кузя."}
    assert body["tools"][0]["function"]["name"] == "notes_list"
    assert body["reasoning"] == {"effort": "low", "exclude": True}


async def test_reasoning_off_is_effort_none() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=_sse(_delta(content="Да.")))

    await _collect(_executor(handler))
    assert bodies[0]["reasoning"] == {"effort": "none", "exclude": True}


async def test_tool_call_fragments_are_joined_at_the_end() -> None:
    first = {"index": 0, "id": "c1", "type": "function", "function": {"name": "calc", "arguments": '{"expr'}}
    rest = {"index": 0, "function": {"arguments": 'ession": "17*23"}'}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_sse(_delta(tool_calls=[first]), _delta(tool_calls=[rest])))

    parts = await _collect(_executor(handler), (TOOL,))
    assert parts == [ReplyPart(tool_call=ToolCall("calc", {"expression": "17*23"}))]


def test_tool_results_reference_their_calls_by_id() -> None:
    history = [
        ChatMessage("user", "Сколько будет 2+2?"),
        ChatMessage("assistant", "", tool_calls=(ToolCall("calc", {"expression": "2+2"}),)),
        ChatMessage("tool", "4", tool_name="calc"),
        ChatMessage("tool", "лишний", tool_name="calc"),
    ]
    payload = messages_payload("П.", history)
    call = payload[2]["tool_calls"][0]
    assert call == {
        "id": "call_1_0",
        "type": "function",
        "function": {"name": "calc", "arguments": '{"expression": "2+2"}'},
    }
    assert payload[2]["content"] is None
    assert payload[3] == {"role": "tool", "tool_call_id": "call_1_0", "content": "4"}
    assert payload[4] == {"role": "user", "content": "Ответ инструмента calc: лишний"}


@pytest.mark.parametrize(
    ("status", "words"),
    [
        (401, "не принял ключ"),
        (402, "закончились деньги"),
        (404, "нет модели «google/gemini-2.5-flash»"),
        (500, "ошибкой 500"),
    ],
)
async def test_http_errors_are_plain_russian_without_key(status: int, words: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": status, "message": "boom"}})

    with pytest.raises(ExecutorError) as error:
        await _collect(_executor(handler, service="OpenRouter"))
    assert words in str(error.value) and "boom" in str(error.value) and KEY not in str(error.value)


async def test_rejected_reasoning_is_retried_once_without_it() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if "reasoning" in bodies[-1]:
            return httpx.Response(400, json={"error": {"code": 400, "message": "Reasoning is mandatory"}})
        return httpx.Response(200, content=_sse(_delta(content="Ок.")))

    executor = _executor(handler, reasoning="high")
    assert [p.text for p in await _collect(executor)] == ["Ок."]
    await _collect(executor)
    assert ["reasoning" in b for b in bodies] == [True, False, False]


async def test_error_inside_stream_and_network_failure() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        chunk = {
            "error": {"code": 502, "message": "provider down"},
            "choices": [{"delta": {}, "finish_reason": "error"}],
        }
        return httpx.Response(200, content=_sse(_delta(content="На"), chunk))

    with pytest.raises(ExecutorError, match="оборвал ответ.*provider down"):
        await _collect(_executor(broken))

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети")

    with pytest.raises(ExecutorError, match="Нет связи с OpenRouter"):
        await _collect(_executor(offline))


async def test_without_key_fails_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("запроса быть не должно")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    executor = CloudExecutor("m", "П.", "https://cloud.test", "", client=client)
    with pytest.raises(ExecutorError, match="Нет ключа OpenRouter"):
        await executor.warm_up()
    with pytest.raises(ExecutorError, match="Нет ключа"):
        await _collect(executor)
    assert executor.models() == frozenset({"@cloud/m"})
