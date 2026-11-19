"""Клиент API ядра: ход текстом и голосом.

Договор (дизайн 2.3; полное описание — README.md, раздел «Как бот говорит с ядром»):
- `POST /api/v1/ask`, JSON `{text, person, source: "telegram"}` → 200 `{answer, turn_id}`;
- `POST /api/v1/ask/voice`, multipart: файл `audio` (OGG/Opus), поля `person`, `source`
  → 200 `{answer, turn_id}`;
- заголовок `Authorization: Bearer <токен ядра>`; 401/403 — токен не принят;
  400/413/422 — ядро отклонило запрос; остальное — ядро недоступно.
"""

from __future__ import annotations

import asyncio
from types import TracebackType
from typing import Any, Self

import httpx

SOURCE = "telegram"
DEFAULT_TIMEOUT = 60.0
_UNAUTHORIZED = {401, 403}
_REJECTED = {400, 413, 422}


class CoreError(Exception):
    """Ход через ядро не удался."""


class CoreUnavailableError(CoreError):
    """Ядро не отвечает, не уложилось во время или ответило непонятно."""


class CoreUnauthorizedError(CoreError):
    """Ядро не приняло токен (401/403)."""


class CoreRejectedError(CoreError):
    """Ядро отклонило запрос (400/413/422): например, не разобрало голосовое."""


class CoreClient:
    """HTTP-клиент ядра. Каждый вызов ограничен `timeout` секундами целиком.

    `transport` — для тестов (поддельное ядро). Прокси из окружения не
    используются: ядро — на этом же Mac или в домашней сети.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
            trust_env=False,
        )

    async def ask(self, text: str, *, person: str) -> str:
        """Ход текстом от имени `person`; возвращает ответ Кузи.

        Ошибки — `CoreUnavailableError`, `CoreUnauthorizedError`, `CoreRejectedError`.
        """
        return await self._post("/api/v1/ask", json={"text": text, "person": person, "source": SOURCE})

    async def ask_voice(self, audio: bytes, *, person: str) -> str:
        """Ход голосовым (OGG/Opus из Telegram) от имени `person`; возвращает ответ Кузи.

        Ошибки — как у `ask`.
        """
        return await self._post(
            "/api/v1/ask/voice",
            files={"audio": ("voice.ogg", audio, "audio/ogg")},
            data={"person": person, "source": SOURCE},
        )

    async def _post(self, path: str, **request: Any) -> str:
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._http.post(path, **request)
        except (TimeoutError, httpx.HTTPError) as error:
            raise CoreUnavailableError(f"ядро не ответило: {type(error).__name__}") from error
        return _answer(response)

    async def aclose(self) -> None:
        """Закрывает соединения."""
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def _answer(response: httpx.Response) -> str:
    """Достаёт `answer` из ответа ядра или поднимает ошибку по коду."""
    status = response.status_code
    if status in _UNAUTHORIZED:
        raise CoreUnauthorizedError(f"ядро ответило {status}")
    if status in _REJECTED:
        raise CoreRejectedError(f"ядро ответило {status}")
    if status != 200:
        raise CoreUnavailableError(f"ядро ответило {status}")
    try:
        body: object = response.json()
    except ValueError as error:
        raise CoreUnavailableError("ядро ответило не JSON") from error
    answer = body.get("answer") if isinstance(body, dict) else None  # type: ignore[union-attr]
    if not isinstance(answer, str):
        raise CoreUnavailableError("в ответе ядра нет строки answer")
    return answer
