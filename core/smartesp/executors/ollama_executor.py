"""Исполнитель на локальной LLM в Ollama."""

import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Iterable, Sequence
from contextlib import aclosing
from typing import Any

import httpx
import ollama

from smartesp.contracts import ChatMessage, ExecutorError, Reasoning, ReplyPart, ToolCall, ToolSpec

_log = logging.getLogger(__name__)

# таймаут HTTP-операций (соединение, запись, чтение вне потока ответа: прогрев, выгрузка) — запрос
# не висит вечно. Не меньше предела прогрева (120 с): холодная большая модель грузится долго.
REQUEST_TIMEOUT_S = 120.0
# таймаут каждого чтения потока ответа (/api/chat): Ollama шлёт заголовки только с первым куском,
# а до него грузит модель, считает промпт или ждёт в очереди за прежним запросом. У каждого, кто
# читает поток, есть свой предел короче этого: у разговора — первый кусок (45 с, цели — 90 с),
# пауза между кусками и предел запоздавшего ответа (600 с от начала хода). Клиент не должен
# обрывать ответ раньше них.
STREAM_READ_TIMEOUT_S = 660.0
THINKING = "thinking"  # возможность модели Ollama рассуждать (show → capabilities)
_warned: set[str] = set()  # модели, о чьём неумении рассуждать уже предупредили
# модели, у которых рассуждение не выключается (think=false они игнорируют и думают на среднем
# уровне), зато есть уровни low/medium/high: им передаём уровень, «off» — самый низкий
_LEVELED_FAMILIES = ("gpt-oss",)


def think_value(model: str, reasoning: Reasoning) -> bool | str:
    """Значение think для Ollama по уровню рассуждения и семейству модели.

    gpt-oss — уровень строкой («off» → «low»: ниже не бывает); остальные — False при «off»,
    иначе True (уровней у них нет). Текст рассуждения в ответ не попадает (см. _chunk_text).
    """
    if any(family in model.lower() for family in _LEVELED_FAMILIES):
        return "low" if reasoning == "off" else reasoning
    return reasoning != "off"


def _chunk_text(chunk: Any) -> str:
    """Достаёт текст ответа из куска (объект ollama или словарь); рассуждение (thinking) не берёт."""
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
        reasoning: Reasoning = "off",
    ) -> None:
        """Запоминает настройки; клиент по умолчанию — локальный ollama.AsyncClient.

        timeout_s — таймаут HTTP-операций клиента по умолчанию, секунды (с client не нужен);
        для потока ответа — свой клиент, у которого чтение ждёт STREAM_READ_TIMEOUT_S.
        reasoning — уровень рассуждения перед ответом (см. think_value).
        """
        self.id = id
        self._reasoning = reasoning
        self._think = think_value(model, reasoning)
        self._model = model
        self._system_prompt = system_prompt
        self._keep_alive = keep_alive
        self._client: Any = client if client is not None else ollama.AsyncClient(timeout=timeout_s)
        self._chat_client: Any = (
            client
            if client is not None
            else ollama.AsyncClient(timeout=httpx.Timeout(timeout_s, read=STREAM_READ_TIMEOUT_S))
        )

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

    def use_thinking(self, supported: bool) -> None:
        """Сообщает, умеет ли модель рассуждать (возможность thinking); не умеет — think=False."""
        if not supported:
            self._without_thinking("у неё нет возможности thinking")

    def _without_thinking(self, why: str) -> None:
        """Дальше без рассуждения; о модели с заданным уровнем — одно предупреждение на процесс."""
        self._think = False
        if self._reasoning != "off" and self._model not in _warned:
            _warned.add(self._model)
            _log.warning(
                "Модель «%s» не умеет рассуждать (%s): уровень «%s» не применяется, отвечает без рассуждения",
                self._model,
                why,
                self._reasoning,
            )

    def _think_rejected(self, exc: ollama.ResponseError) -> bool:
        """True, если Ollama отклонила think (400 «… does not support thinking»): дальше без него."""
        if self._think is False or exc.status_code != 400 or "think" not in str(exc.error).lower():
            return False
        self._without_thinking(f"Ollama: {exc.error}")
        return True

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
        extra: dict[str, Any] = {"tools": [_tool_payload(t) for t in tools]} if tools else {}
        try:
            gave = False
            try:
                async with aclosing(self._chat(payload, extra)) as parts:
                    async for part in parts:
                        gave = True
                        yield part
            except ollama.ResponseError as exc:
                if gave or not self._think_rejected(exc):
                    raise
                async with aclosing(self._chat(payload, extra)) as parts:  # один повтор, уже без think
                    async for part in parts:
                        yield part
        except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
            raise self._wrap_error(exc) from exc

    async def _chat(self, payload: list[dict[str, Any]], extra: dict[str, Any]) -> AsyncGenerator[ReplyPart]:
        """Один запрос /api/chat потоком: непустые куски текста и вызовы инструментов."""
        stream = await self._chat_client.chat(
            model=self._model,
            messages=payload,
            stream=True,
            think=self._think,
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

    async def warm_up(self) -> None:
        """Загружает модель в память пустым запросом (без генерации текста), с тем же think, что ход.

        Отклонённый think — как в ходе: один повтор без него. Кидает ExecutorError, если Ollama
        недоступна или модели нет.
        """
        try:
            try:
                await self._generate_empty()
            except ollama.ResponseError as exc:
                if not self._think_rejected(exc):
                    raise
                await self._generate_empty()
        except (httpx.HTTPError, ConnectionError, ollama.ResponseError) as exc:
            raise self._wrap_error(exc) from exc

    async def _generate_empty(self) -> None:
        """Пустой generate: только загрузка модели."""
        await self._client.generate(
            model=self._model, prompt="", keep_alive=self._keep_alive, think=self._think
        )

    async def unload(self, timeout_s: float = 1.0) -> None:
        """Выгружает модель из памяти (keep_alive=0), ждёт не дольше timeout_s секунд.

        Не кидает исключений: ошибка или таймаут — только предупреждение в журнал.
        """
        try:
            async with asyncio.timeout(timeout_s):
                await self._client.generate(model=self._model, prompt="", keep_alive=0)
        except Exception as exc:  # noqa: BLE001 — выгрузка не должна ломать остановку
            _log.warning("Не удалось выгрузить модель «%s»: %r", self._model, exc)
