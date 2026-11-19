"""Исполнитель на локальной LLM в Ollama."""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import aclosing
from typing import Any

import httpx
import ollama

from smartesp.contracts import ChatMessage, ExecutorError, ReplyPart, ToolCall, ToolSpec

_log = logging.getLogger(__name__)

# таймаут HTTP-операций (соединение, каждое чтение) — запрос не висит вечно. Не меньше предела
# первого куска цели передачи (90 с) с запасом и предела прогрева (120 с): холодная большая модель
# грузится долго, и клиент не должен оборвать её раньше этих пределов. Входному исполнителю
# раньше обрыва срабатывает собственный предел оркестратора (45 с на первый кусок).
REQUEST_TIMEOUT_S = 120.0


def _chunk_text(chunk: Any) -> str:
    """Достаёт текст из куска ответа (объект ollama или словарь)."""
    message = chunk["message"] if isinstance(chunk, dict) else chunk.message
    if message is None:
        return ""
    content = message["content"] if isinstance(message, dict) else message.content
    return content or ""


def _get(item: Any, name: str) -> Any:
    """Читает поле из объекта ollama или словаря."""
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _chunk_tool_calls(chunk: Any) -> list[ToolCall]:
    """Достаёт вызовы инструментов из куска ответа (объект ollama или словарь)."""
    message = _get(chunk, "message")
    calls: list[ToolCall] = []
    for raw in (_get(message, "tool_calls") if message is not None else None) or []:
        fn = _get(raw, "function")
        name = _get(fn, "name")
        if name:
            calls.append(ToolCall(str(name), dict(_get(fn, "arguments") or {})))
    return calls


def _tool_payload(tool: ToolSpec) -> dict[str, Any]:
    """Описание инструмента в формате chat(tools=...)."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    """Сообщение в формате chat(messages=...): с вызовами инструментов и именем инструмента."""
    payload: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {"function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
        ]
    if message.tool_name:
        payload["tool_name"] = message.tool_name
    return payload


class OllamaExecutor:
    """Отвечает на диалог моделью из Ollama, отдавая текст по кускам."""

    def __init__(
        self,
        model: str,
        system_prompt: str,
        keep_alive: str,
        client: Any = None,
        timeout_s: float = REQUEST_TIMEOUT_S,
        *,
        id: str = "",  # noqa: A002 — имя поля задано контрактом Identified
    ) -> None:
        """Запоминает настройки; клиент по умолчанию — локальный ollama.AsyncClient.

        timeout_s — таймаут HTTP-операций клиента по умолчанию, секунды (с client не нужен).
        """
        self.id = id
        self._model = model
        self._system_prompt = system_prompt
        self._keep_alive = keep_alive
        self._client: Any = client if client is not None else ollama.AsyncClient(timeout=timeout_s)

    @property
    def model(self) -> str:
        """Имя модели этого исполнителя."""
        return self._model

    def models(self) -> frozenset[str]:
        """Имена моделей, которые держит исполнитель."""
        return frozenset({self._model})

    async def unload_models(self, names: Iterable[str], timeout_s: float = 1.0) -> None:
        """Выгружает свою модель, если она есть среди names; не бросает исключений."""
        if self._model in set(names):
            await self.unload(timeout_s)

    def _wrap_error(self, exc: Exception) -> ExecutorError:
        """Превращает ошибку ollama/сети в понятную ExecutorError."""
        if isinstance(exc, ollama.ResponseError):
            return ExecutorError(
                f"Ollama отклонила запрос к модели «{self._model}»: {exc.error} "
                f"(если модели нет — выполните: ollama pull {self._model})"
            )
        return ExecutorError(
            f"Не удалось связаться с Ollama для модели «{self._model}»: {exc!r}. "
            "Проверьте, что сервер Ollama запущен."
        )

    async def run(
        self, messages: list[ChatMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[ReplyPart]:
        """Отправляет системный промпт и диалог в модель, отдаёт непустые куски ответа.

        Инструменты tools передаются модели; её вызовы приходят кусками с tool_call.
        Кидает ExecutorError, если Ollama недоступна или модели нет.
        """
        payload = [{"role": "system", "content": self._system_prompt}]
        payload += [_message_payload(m) for m in messages]
        try:
            extra: dict[str, Any] = {"tools": [_tool_payload(t) for t in tools]} if tools else {}
            stream = await self._client.chat(
                model=self._model,
                messages=payload,
                stream=True,
                think=False,
                keep_alive=self._keep_alive,
                **extra,
            )
            # aclosing закрывает HTTP-поток и при раннем выходе (barge-in)
            async with aclosing(stream):
                async for chunk in stream:
                    text = _chunk_text(chunk)
                    if text:
                        yield ReplyPart(text)
                    for call in _chunk_tool_calls(chunk):
                        yield ReplyPart(tool_call=call)
        except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
            raise self._wrap_error(exc) from exc

    async def warm_up(self) -> None:
        """Загружает модель в память пустым запросом (без генерации текста).

        Кидает ExecutorError, если Ollama недоступна или модели нет.
        """
        try:
            await self._client.generate(model=self._model, prompt="", keep_alive=self._keep_alive)
        except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
            raise self._wrap_error(exc) from exc

    async def unload(self, timeout_s: float = 1.0) -> None:
        """Выгружает модель из памяти (keep_alive=0), ждёт не дольше timeout_s секунд.

        Не кидает исключений: ошибка или таймаут — только предупреждение в журнал.
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self._client.generate(model=self._model, prompt="", keep_alive=0)
        except Exception as exc:  # noqa: BLE001 — выгрузка не должна ломать остановку
            _log.warning("Не удалось выгрузить модель «%s»: %r", self._model, exc)
