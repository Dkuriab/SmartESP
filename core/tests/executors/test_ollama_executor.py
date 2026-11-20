"""Тесты OllamaExecutor."""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import ollama
import pytest

from smartesp.contracts import ChatMessage, Executor, ExecutorError
from smartesp.conversation.handoffs import DELEGATE_FIRST_PART_LIMIT_S
from smartesp.conversation.late import LATE_LIMIT_S
from smartesp.executors import OllamaExecutor
from smartesp.executors.ollama_executor import REQUEST_TIMEOUT_S, STREAM_READ_TIMEOUT_S
from smartesp.wiring import WARM_UP_TIMEOUT_S


class FakeClient:
    def __init__(self, parts: list[str] | None = None, error: Exception | None = None) -> None:
        self.parts = parts or []
        self.error = error
        self.chat_kwargs: dict[str, Any] = {}
        self.generate_kwargs: dict[str, Any] = {}
        self.stream_closed = False
        self.mid_error: Exception | None = None

    async def chat(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        self.chat_kwargs = kwargs
        if self.error:
            raise self.error
        return self._stream()

    async def _stream(self) -> AsyncIterator[dict[str, Any]]:
        try:
            for p in self.parts:
                yield {"message": {"content": p}}
            if self.mid_error:
                raise self.mid_error
        finally:
            self.stream_closed = True

    async def generate(self, **kwargs: Any) -> None:
        self.generate_kwargs = kwargs
        if self.error:
            raise self.error


def make(client: FakeClient) -> OllamaExecutor:
    return OllamaExecutor("m", "Ты помощник.", "30m", client)


async def collect(ex: OllamaExecutor) -> list[str]:
    return [p.text async for p in ex.run([ChatMessage("user", "привет")])]


def test_satisfies_executor_protocol() -> None:
    ex: Executor = make(FakeClient())
    assert ex is not None


async def test_streams_parts_skipping_empty() -> None:
    assert await collect(make(FakeClient(["При", "", "вет"]))) == ["При", "вет"]


async def test_prepends_system_prompt() -> None:
    c = FakeClient(["x"])
    await collect(make(c))
    msgs = c.chat_kwargs["messages"]
    assert msgs[0] == {"role": "system", "content": "Ты помощник."}
    assert msgs[1] == {"role": "user", "content": "привет"}


async def test_passes_think_false_and_keep_alive() -> None:
    c = FakeClient(["x"])
    await collect(make(c))
    assert c.chat_kwargs["think"] is False
    assert c.chat_kwargs["keep_alive"] == "30m"
    assert c.chat_kwargs["stream"] is True
    assert c.chat_kwargs["model"] == "m"


async def test_connection_error_becomes_executor_error() -> None:
    with pytest.raises(ExecutorError, match="«m»"):
        await collect(make(FakeClient(error=httpx.ConnectError("нет связи"))))


async def test_stream_closed_on_early_stop() -> None:
    c = FakeClient(["a", "b", "c"])
    gen = make(c).run([ChatMessage("user", "привет")])
    async for _ in gen:
        break
    await gen.aclose()  # type: ignore[attr-defined]
    assert c.stream_closed


async def test_mid_stream_error_becomes_executor_error() -> None:
    c = FakeClient(["a"])
    c.mid_error = httpx.ReadError("обрыв")
    with pytest.raises(ExecutorError, match="«m»"):
        await collect(make(c))
    assert c.stream_closed


async def test_missing_model_becomes_executor_error() -> None:
    with pytest.raises(ExecutorError, match="ollama pull"):
        await collect(make(FakeClient(error=ollama.ResponseError("not found", 404))))


async def test_warm_up_calls_generate_and_wraps_errors() -> None:
    c = FakeClient()
    await make(c).warm_up()
    assert c.generate_kwargs["keep_alive"] == "30m"
    with pytest.raises(ExecutorError):
        await make(FakeClient(error=httpx.ConnectError("x"))).warm_up()


def test_default_client_has_timeout() -> None:
    ex = OllamaExecutor("m", "Ты помощник.", "30m", timeout_s=12.5)
    assert ex._client._client.timeout == httpx.Timeout(12.5)  # type: ignore[attr-defined]
    assert OllamaExecutor("m", "", "30m")._client._client.timeout == httpx.Timeout(120.0)  # type: ignore[attr-defined]


def test_default_read_timeout_outlasts_handoff_limit_and_warm_up() -> None:
    # цель передачи: обрыв чтения раньше предела 90 с дал бы «не отвечает» вместо фразы о сроке;
    # прогрев участника (120 с) не должен обрываться клиентом раньше своего предела
    assert REQUEST_TIMEOUT_S >= DELEGATE_FIRST_PART_LIMIT_S + 10
    assert REQUEST_TIMEOUT_S >= WARM_UP_TIMEOUT_S


def test_chat_stream_read_timeout_outlasts_late_answer_limit() -> None:
    # отложенный ответ цели ждём до 600 с от начала хода: холодная модель или очередь в Ollama
    # не должны обрываться клиентом через 120 с без первого куска
    ex = OllamaExecutor("m", "", "30m", timeout_s=12.5)
    assert ex._chat_client._client.timeout == httpx.Timeout(12.5, read=STREAM_READ_TIMEOUT_S)  # type: ignore[attr-defined]
    # прогрев и выгрузка — как были
    assert ex._client._client.timeout == httpx.Timeout(12.5)  # type: ignore[attr-defined]
    assert STREAM_READ_TIMEOUT_S >= LATE_LIMIT_S + 30


async def test_chat_waits_for_slow_first_token_beyond_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # настоящий HTTP на 127.0.0.1: «Ollama» молчит дольше REQUEST_TIMEOUT_S (здесь 0,05 с)
    # до первого куска — поток ответа не обрывается, а прогрев с тем же молчанием обрывается
    body = '{"message": {"role": "assistant", "content": "Готово."}, "done": true}\n'.encode()

    async def slow_ollama(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        await asyncio.sleep(0.3)
        head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        try:
            writer.write(head.encode() + body)
            await writer.drain()
        except ConnectionError:  # прогрев уже оборвал соединение
            pass
        writer.close()

    server = await asyncio.start_server(slow_ollama, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setenv("OLLAMA_HOST", f"http://127.0.0.1:{port}")
    try:
        ex = OllamaExecutor("m", "", "30m", timeout_s=0.05)
        assert [p.text async for p in ex.run([ChatMessage("user", "Вопрос")])] == ["Готово."]
        with pytest.raises(ExecutorError):
            await ex.warm_up()
    finally:
        server.close()
        await server.wait_closed()


async def test_read_timeout_becomes_executor_error() -> None:
    with pytest.raises(ExecutorError, match="«m»"):
        await collect(make(FakeClient(error=httpx.ReadTimeout("долго"))))


@pytest.mark.models
async def test_real_ollama_streams_answer() -> None:
    model = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive"
    ex = OllamaExecutor(model, "Отвечай кратко.", "5m")
    await ex.warm_up()
    start = time.monotonic()
    first: float | None = None
    text = ""
    async for part in ex.run([ChatMessage("user", "Ответь одним словом: столица Франции?")]):
        if first is None:
            first = time.monotonic() - start
        text += part.text
    print(f"\nanswer={text!r} first_token={first:.2f}s total={time.monotonic() - start:.2f}s")
    assert "париж" in text.lower()


async def test_unload_sends_keep_alive_zero() -> None:
    client = FakeClient()
    ex = make(client)
    await ex.unload()
    assert client.generate_kwargs == {"model": "m", "prompt": "", "keep_alive": 0}
    assert ex.model == "m"


async def test_unload_swallows_error(caplog: pytest.LogCaptureFixture) -> None:
    await make(FakeClient(error=httpx.ConnectError("x"))).unload()
    assert "выгрузить" in caplog.text


async def test_unload_times_out_on_hang(caplog: pytest.LogCaptureFixture) -> None:
    class Hanging(FakeClient):
        async def generate(self, **kwargs: Any) -> None:
            await asyncio.sleep(10)

    start = time.monotonic()
    await make(Hanging()).unload(timeout_s=0.1)
    assert time.monotonic() - start < 1.0
    assert any(r.levelname == "WARNING" for r in caplog.records)


# ---- уровень рассуждения (W3-6) ----


@pytest.mark.parametrize(
    ("model", "reasoning", "think"),
    [
        ("qwen3:8b", "off", False),
        ("qwen3:8b", "low", True),
        ("qwen3:8b", "high", True),
        ("gpt-oss:20b", "low", "low"),
        ("gpt-oss:20b", "medium", "medium"),
        ("gpt-oss:120b", "high", "high"),
        # gpt-oss не умеет выключать рассуждение: false он игнорирует и думает на среднем уровне
        ("gpt-oss:20b", "off", "low"),
        ("someone/GPT-OSS-20B-custom", "medium", "medium"),
    ],
)
async def test_reasoning_maps_to_think_per_model_family(model: str, reasoning: str, think: object) -> None:
    c = FakeClient(["x"])
    ex = OllamaExecutor(model, "Ты помощник.", "30m", c, reasoning=reasoning)  # type: ignore[arg-type]
    await collect(ex)
    assert c.chat_kwargs["think"] == think


async def test_reasoning_defaults_to_off() -> None:
    c = FakeClient(["x"])
    await collect(make(c))
    assert c.chat_kwargs["think"] is False


async def test_thinking_text_is_never_yielded() -> None:
    class Thinking(FakeClient):
        async def _stream(self) -> AsyncIterator[dict[str, Any]]:
            yield {"message": {"content": "", "thinking": "Человек просит таймер…"}}
            yield {"message": {"content": "Готово.", "thinking": "ещё мысли"}}

    c = Thinking()
    ex = OllamaExecutor("gpt-oss:20b", "Ты помощник.", "30m", c, reasoning="low")
    parts = [p async for p in ex.run([ChatMessage("user", "привет")])]
    assert [p.text for p in parts] == ["Готово."]
