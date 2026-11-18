"""Исполнитель на локальной LLM в Ollama."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

import httpx
import ollama

from smartesp.contracts import ChatMessage, ExecutorError, ReplyPart

REQUEST_TIMEOUT_S = 60.0  # таймаут HTTP-операций (соединение, каждое чтение) — запрос не висит вечно


def _chunk_text(chunk: Any) -> str:
    """Достаёт текст из куска ответа (объект ollama или словарь)."""
    message = chunk["message"] if isinstance(chunk, dict) else chunk.message
    if message is None:
        return ""
    content = message["content"] if isinstance(message, dict) else message.content
    return content or ""


class OllamaExecutor:
    """Отвечает на диалог моделью из Ollama, отдавая текст по кускам."""

    def __init__(
        self,
        model: str,
        system_prompt: str,
        keep_alive: str,
        client: Any = None,
        timeout_s: float = REQUEST_TIMEOUT_S,
    ) -> None:
        """Запоминает настройки; клиент по умолчанию — локальный ollama.AsyncClient.

        timeout_s — таймаут HTTP-операций клиента по умолчанию, секунды (с client не нужен).
        """
        self._model = model
        self._system_prompt = system_prompt
        self._keep_alive = keep_alive
        self._client: Any = client if client is not None else ollama.AsyncClient(timeout=timeout_s)

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

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[ReplyPart]:
        """Отправляет системный промпт и диалог в модель, отдаёт непустые куски ответа.

        Кидает ExecutorError, если Ollama недоступна или модели нет.
        """
        payload = [{"role": "system", "content": self._system_prompt}]
        payload += [{"role": m.role, "content": m.content} for m in messages]
        try:
            stream = await self._client.chat(
                model=self._model,
                messages=payload,
                stream=True,
                think=False,
                keep_alive=self._keep_alive,
            )
            # aclosing закрывает HTTP-поток и при раннем выходе (barge-in)
            async with aclosing(stream):
                async for chunk in stream:
                    text = _chunk_text(chunk)
                    if text:
                        yield ReplyPart(text)
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
