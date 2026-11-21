"""Исполнитель на модели облачного сервиса с OpenAI-совместимым API (OpenRouter и т. п.)."""

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Sequence
from contextlib import aclosing
from typing import Any, cast

import httpx

from smartesp.contracts import (
    CLOUD_MODEL_PREFIX,
    ChatMessage,
    ExecutorError,
    Reasoning,
    ReplyPart,
    ToolCall,
    ToolSpec,
)

from .ollama_executor import STREAM_READ_TIMEOUT_S

_log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 10.0  # соединение и отправка запроса; чтение потока — STREAM_READ_TIMEOUT_S
# понятный текст по коду ответа сервиса ({s} — имя сервиса, {m} — модель)
_STATUS_TEXT = {
    401: "{s} не принял ключ — проверьте его в настройках ядра",
    402: "на счёте {s} закончились деньги",
    403: "{s} отказал в запросе (ограничение ключа или модерация)",
    404: "у {s} нет модели «{m}» или она не умеет инструменты",
    408: "{s} не дождался ответа модели",
    429: "{s}: слишком много запросов, подождите",
    502: "модель «{m}» у {s} сейчас недоступна",
    503: "у {s} нет свободного поставщика для модели «{m}»",
}


def effort(reasoning: Reasoning) -> str:
    """reasoning.effort для сервиса: «off» — «none» (не рассуждать), иначе тот же уровень."""
    return "none" if reasoning == "off" else reasoning


def _tool_payload(tool: ToolSpec) -> dict[str, Any]:
    """Инструмент в формате tools OpenAI."""
    function = {"name": tool.name, "description": tool.description, "parameters": tool.parameters}
    return {"type": "function", "function": function}


def _take_call(pending: list[tuple[str, str]], name: str) -> str | None:
    """id ожидающего вызова с этим именем (иначе первого); нет ожидающих — None."""
    for index, (_, call_name) in enumerate(pending):
        if call_name == name:
            return pending.pop(index)[0]
    return pending.pop(0)[0] if pending else None


def messages_payload(system_prompt: str, messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    """Диалог в формате OpenAI: вызовам инструментов даются id, ответы инструментов ссылаются на них.

    Ответ инструмента без вызова перед ним (так история не бывает, но вдруг) — сообщение user
    с текстом ответа: API отклонил бы tool без tool_call_id.
    """
    payload: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    pending: list[tuple[str, str]] = []
    for i, message in enumerate(messages):
        if message.role == "assistant" and message.tool_calls:
            ids = [f"call_{i}_{j}" for j in range(len(message.tool_calls))]
            pending = [(call_id, c.name) for call_id, c in zip(ids, message.tool_calls, strict=True)]
            calls = [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments, ensure_ascii=False)},
                }
                for call_id, c in zip(ids, message.tool_calls, strict=True)
            ]
            payload.append({"role": "assistant", "content": message.content or None, "tool_calls": calls})
        elif message.role == "tool":
            call_id = _take_call(pending, message.tool_name)
            if call_id is None:
                payload.append(
                    {"role": "user", "content": f"Ответ инструмента {message.tool_name}: {message.content}"}
                )
            else:
                payload.append({"role": "tool", "tool_call_id": call_id, "content": message.content})
        else:
            payload.append({"role": message.role, "content": message.content})
    return payload


def _arguments(raw: object) -> dict[str, object]:
    """Аргументы вызова: JSON-строка или словарь; неразборчивое — пустой словарь."""
    if isinstance(raw, dict):
        return cast(dict[str, object], raw)
    try:
        parsed = json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], parsed) if isinstance(parsed, dict) else {}


def _error_detail(body: bytes) -> str:
    """Текст ошибки из тела ответа {"error": {"message": …}} или начало тела."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body[:200].decode("utf-8", "replace").strip()
    error = data.get("error") if isinstance(data, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    return str(message) if message else str(data)[:200]


class _Calls:
    """Вызовы инструментов, собранные из кусков потока (по index: имя и части аргументов)."""

    def __init__(self) -> None:
        self._slots: dict[int, list[str]] = {}

    def add(self, delta: dict[str, Any]) -> None:
        """Добавляет части вызовов из delta.tool_calls."""
        for raw in delta.get("tool_calls") or []:
            call = cast(dict[str, Any], raw)
            slot = self._slots.setdefault(int(call.get("index") or 0), ["", ""])
            function = cast(dict[str, Any], call.get("function") or {})
            if function.get("name") and not slot[0]:
                slot[0] = str(function["name"])
            arguments = function.get("arguments")
            if isinstance(arguments, dict):
                slot[1] = json.dumps(arguments)
            elif arguments:
                slot[1] += str(arguments)

    def parts(self) -> list[ReplyPart]:
        """Готовые вызовы по порядку; без имени — пропускаются."""
        return [
            ReplyPart(tool_call=ToolCall(name, _arguments(args)))
            for name, args in (self._slots[i] for i in sorted(self._slots))
            if name
        ]


class CloudExecutor:
    """Отвечает моделью облачного сервиса потоком chat/completions (SSE)."""

    def __init__(
        self,
        model: str,
        system_prompt: str,
        base_url: str,
        api_key: str,
        *,
        id: str = "",  # noqa: A002 — имя поля задано контрактом Identified
        reasoning: Reasoning = "off",
        service: str = "OpenRouter",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """model — id модели сервиса; base_url — адрес API (…/api/v1); api_key — ключ сервиса;
        service — имя сервиса для текстов ошибок; client — свой HTTP-клиент (тесты).
        """
        self.id = id
        self._model = model
        self._system_prompt = system_prompt
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._reasoning: Reasoning = reasoning
        self._send_reasoning = True
        self._service = service
        self._client = client

    def models(self) -> frozenset[str]:
        """Имя модели в сети исполнителей: «@cloud/<id>» (в памяти Ollama её нет)."""
        return frozenset({CLOUD_MODEL_PREFIX + self._model})

    async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None:
        """Облачную модель выгружать неоткуда: ничего не делает."""

    async def warm_up(self) -> None:
        """Проверяет только, что ключ задан (запрос к модели стоил бы денег); нет — ExecutorError."""
        if not self._key:
            raise ExecutorError(f"Нет ключа {self._service}: введите его в настройках ядра")

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(CONNECT_TIMEOUT_S, read=STREAM_READ_TIMEOUT_S)
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    def _body(self, messages: list[ChatMessage], tools: Sequence[ToolSpec]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages_payload(self._system_prompt, messages),
            "stream": True,
        }
        if tools:
            body["tools"] = [_tool_payload(t) for t in tools]
        if self._send_reasoning:
            body["reasoning"] = {"effort": effort(self._reasoning), "exclude": True}
        return body

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        """Отдаёт куски текста и (в конце) вызовы инструментов; сбой — ExecutorError с понятным текстом.

        Сервис отклонил рассуждение (модель без него или с обязательным) — один повтор без поля
        reasoning, дальше этот исполнитель его не шлёт.
        """
        await self.warm_up()
        try:
            async with aclosing(self._stream(self._body(messages, tools))) as parts:
                async for part in parts:
                    yield part
        except _ReasoningRejectedError:
            self._send_reasoning = False
            _log.warning("%s: модель «%s» не приняла reasoning — дальше без него", self._service, self._model)
            async with aclosing(self._stream(self._body(messages, tools))) as parts:
                async for part in parts:
                    yield part

    async def _stream(self, body: dict[str, Any]) -> AsyncGenerator[ReplyPart]:
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            async with self._http().stream("POST", self._url, json=body, headers=headers) as response:
                if response.status_code != httpx.codes.OK:
                    raise self._status_error(
                        response.status_code, await response.aread(), "reasoning" in body
                    )
                calls = _Calls()
                async for line in response.aiter_lines():
                    for part in self._line_parts(line, calls):
                        yield part
                    if line.strip() == "data: [DONE]":
                        break
                for part in calls.parts():
                    yield part
        except httpx.HTTPError as exc:
            raise ExecutorError(f"Нет связи с {self._service}: {type(exc).__name__}") from exc

    def _line_parts(self, line: str, calls: _Calls) -> list[ReplyPart]:
        """Текст из строки SSE «data: {…}»; вызовы копятся в calls; ошибка в потоке — ExecutorError."""
        if not line.startswith("data:") or line.strip() == "data: [DONE]":
            return []  # «: OPENROUTER PROCESSING» и пустые строки — служебные
        try:
            chunk = json.loads(line[5:])
        except json.JSONDecodeError:
            return []
        if not isinstance(chunk, dict):
            return []
        data = cast(dict[str, Any], chunk)
        if data.get("error"):
            detail = _error_detail(json.dumps(data).encode())
            raise ExecutorError(f"{self._service} оборвал ответ модели «{self._model}»: {detail}")
        parts: list[ReplyPart] = []
        for choice in data.get("choices") or []:
            delta = cast(dict[str, Any], cast(dict[str, Any], choice).get("delta") or {})
            if delta.get("content"):
                parts.append(ReplyPart(str(delta["content"])))
            calls.add(delta)
        return parts

    def _status_error(self, status: int, body: bytes, sent_reasoning: bool) -> Exception:
        detail = _error_detail(body)
        if status == httpx.codes.BAD_REQUEST and sent_reasoning and "reasoning" in detail.lower():
            return _ReasoningRejectedError()
        text = _STATUS_TEXT.get(status, "{s} ответил ошибкой " + str(status))
        return ExecutorError(f"{text.format(s=self._service, m=self._model)}: {detail}")


class _ReasoningRejectedError(Exception):
    """Сервис отклонил поле reasoning: повторить без него."""
