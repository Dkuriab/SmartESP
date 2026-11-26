"""Общий исполнитель на OpenAI-совместимом API: поток chat/completions (SSE) с инструментами.

Наследники (облако, LM Studio) задают поля рассуждения, тексты ошибок и прочие поля запроса.
"""

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Sequence
from contextlib import aclosing
from typing import Any, Protocol, cast

import httpx

from smartesp.contracts import ChatMessage, ExecutorError, Reasoning, ReplyPart, ToolSpec

from .ollama_executor import STREAM_READ_TIMEOUT_S
from .openai_format import DONE, ToolCallParts, error_detail, messages_payload, sse_chunk, tool_payload

_log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 10.0  # соединение и отправка запроса; чтение потока — STREAM_READ_TIMEOUT_S


class TextFilter(Protocol):
    """Фильтр текста потока: что из куска отдавать модели в ответ."""

    def feed(self, text: str) -> str:
        """Часть куска, которую можно отдать сейчас."""
        ...

    def end(self) -> str:
        """Остаток в конце потока."""
        ...


class _PlainText:
    """Текст как есть."""

    def feed(self, text: str) -> str:
        return text

    def end(self) -> str:
        return ""


class ReasoningRejectedError(Exception):
    """Сервис отклонил поле рассуждения: повторить без него."""


class OpenAIChatExecutor:
    """Отвечает моделью OpenAI-совместимого сервиса потоком chat/completions (SSE)."""

    model_prefix = ""  # приставка имени модели в сети исполнителей («@cloud/» и т. п.)

    def __init__(
        self,
        model: str,
        system_prompt: str,
        url: str,
        api_key: str,
        *,
        id: str = "",  # noqa: A002 — имя поля задано контрактом Identified
        reasoning: Reasoning = "off",
        service: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """url — полный адрес chat/completions; api_key — ключ (пусто — без заголовка Authorization);
        service — имя сервиса для текстов ошибок; client — свой HTTP-клиент (тесты).
        """
        self.id = id
        self._model = model
        self._system_prompt = system_prompt
        self._url = url
        self._key = api_key
        self._reasoning: Reasoning = reasoning
        self._send_reasoning = True
        self._service = service
        self._client = client

    def models(self) -> frozenset[str]:
        """Имя модели в сети исполнителей: приставка вида + id (в памяти Ollama её нет)."""
        return frozenset({self.model_prefix + self._model})

    async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None:
        """Модели Ollama этот исполнитель не держит: ничего не делает."""

    # --- крючки наследников ---

    def _check_ready(self) -> None:
        """Проверка перед ходом (например, задан ли ключ); не готов — ExecutorError."""

    def _reasoning_fields(self) -> dict[str, Any]:
        """Поля рассуждения в запросе (пусто — не шлются)."""
        return {}

    def _extra_fields(self) -> dict[str, Any]:
        """Прочие поля запроса сверх стандартных."""
        return {}

    def _text_filter(self) -> TextFilter:
        """Фильтр текста на один поток ответа."""
        return _PlainText()

    def _error_text(self, status: int, detail: str) -> str:
        """Понятный текст ошибки по коду ответа (detail — текст сервиса, добавляется после)."""
        return f"{self._service} ответил ошибкой {status}"

    def _connect_error(self, exc: httpx.HTTPError) -> ExecutorError:
        """Ошибка связи с сервисом."""
        return ExecutorError(f"Нет связи с {self._service}: {type(exc).__name__}")

    # --- общий ход ---

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(CONNECT_TIMEOUT_S, read=STREAM_READ_TIMEOUT_S)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}"} if self._key else {}

    def _body(self, messages: list[ChatMessage], tools: Sequence[ToolSpec]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages_payload(self._system_prompt, messages),
            "stream": True,
            **self._extra_fields(),
        }
        if tools:
            body["tools"] = [tool_payload(t) for t in tools]
        if self._send_reasoning:
            body.update(self._reasoning_fields())
        return body

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        """Отдаёт куски текста и (в конце) вызовы инструментов; сбой — ExecutorError с понятным текстом.

        Сервис отклонил рассуждение (модель без него или с обязательным) — один повтор без полей
        рассуждения, дальше этот исполнитель их не шлёт.
        """
        self._check_ready()
        try:
            async with aclosing(self._stream(self._body(messages, tools))) as parts:
                async for part in parts:
                    yield part
        except ReasoningRejectedError:
            self._send_reasoning = False
            _log.warning("%s: «%s» не приняла рассуждение — дальше без него", self._service, self._model)
            async with aclosing(self._stream(self._body(messages, tools))) as parts:
                async for part in parts:
                    yield part

    async def _stream(self, body: dict[str, Any]) -> AsyncGenerator[ReplyPart]:
        sent_reasoning = self._send_reasoning and bool(self._reasoning_fields())
        try:
            async with self._http().stream("POST", self._url, json=body, headers=self._headers()) as response:
                if response.status_code != httpx.codes.OK:
                    raise self._status_error(response.status_code, await response.aread(), sent_reasoning)
                calls, text = ToolCallParts(), self._text_filter()
                async for line in response.aiter_lines():
                    for part in self._line_parts(line, calls, text):
                        yield part
                    if line.strip() == DONE:
                        break
                if rest := text.end():
                    yield ReplyPart(rest)
                for part in calls.parts():
                    yield part
        except httpx.HTTPError as exc:
            raise self._connect_error(exc) from exc

    def _line_parts(self, line: str, calls: ToolCallParts, text: TextFilter) -> list[ReplyPart]:
        """Текст из строки SSE; вызовы копятся в calls; ошибка в потоке — ExecutorError."""
        data = sse_chunk(line)
        if data is None:
            return []
        if data.get("error"):
            detail = error_detail(json.dumps(data).encode())
            raise ExecutorError(f"{self._service} оборвал ответ модели «{self._model}»: {detail}")
        parts: list[ReplyPart] = []
        for choice in data.get("choices") or []:
            delta = cast(dict[str, Any], cast(dict[str, Any], choice).get("delta") or {})
            if delta.get("content") and (shown := text.feed(str(delta["content"]))):
                parts.append(ReplyPart(shown))
            calls.add(delta)
        return parts

    def _status_error(self, status: int, body: bytes, sent_reasoning: bool) -> Exception:
        detail = error_detail(body)
        if status == httpx.codes.BAD_REQUEST and sent_reasoning and "reasoning" in detail.lower():
            return ReasoningRejectedError()
        return ExecutorError(f"{self._error_text(status, detail)}: {detail}")
