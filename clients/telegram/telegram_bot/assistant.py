"""Логика бота без Telegram: кто допущен, что отправить ядру, что ответить в чат."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

from .barcode import find_barcode
from .core_client import CoreRejectedError, CoreUnauthorizedError, CoreUnavailableError

log = logging.getLogger(__name__)

NO_BARCODE = "Не вижу штрихкод на фото. Сфотографируй его ближе."
CORE_UNAVAILABLE = "Кузя сейчас недоступен."
CORE_UNAUTHORIZED = "Кузя не пускает бота — проверь токен."
CORE_REJECTED = "Не получилось разобрать сообщение — попробуй ещё раз."
CORE_EMPTY = "Кузя ничего не ответил."


class Core(Protocol):
    """Ход через ядро (реализация — `CoreClient`, в тестах — подделка)."""

    async def ask(self, text: str, *, person: str, account: str = "") -> str:
        """Ход текстом (account — user_id в Telegram строкой); возвращает ответ Кузи."""
        ...

    async def ask_voice(self, audio: bytes, *, person: str, account: str = "") -> str:
        """Ход голосовым OGG/Opus; возвращает ответ Кузи."""
        ...


class Assistant:
    """Превращает сообщения допущенных людей в ходы ядра и ответы в чат.

    `users` — `user_id` Telegram → имя человека; `barcode_reader` — поиск
    штрихкода на фото (подменяется в тестах).
    """

    def __init__(
        self,
        core: Core,
        users: dict[int, str],
        *,
        barcode_reader: Callable[[bytes], str | None] = find_barcode,
    ) -> None:
        self._core = core
        self._users = dict(users)
        self._read_barcode = barcode_reader

    def person(self, user_id: int | None) -> str | None:
        """Имя человека для допущенного `user_id`; чужой или неизвестный — None."""
        if user_id is None:
            return None
        return self._users.get(user_id)

    async def text(self, person: str, text: str, account: str = "") -> str:
        """Текстовое сообщение → ход ядра; возвращает текст ответа в чат.

        account — `user_id` отправителя строкой: по нему ядро узнаёт человека из «Людей».
        """
        return await self._turn(self._core.ask(text, person=person, account=account))

    async def voice(self, person: str, audio: bytes, account: str = "") -> str:
        """Голосовое (OGG/Opus) → ход ядра; возвращает текст ответа в чат."""
        return await self._turn(self._core.ask_voice(audio, person=person, account=account))

    async def photo(self, person: str, photo: bytes, caption: str | None, account: str = "") -> str:
        """Фото: найден штрихкод → ход «штрихкод <код>, <подпись>»; нет — просьба переснять."""
        code = await asyncio.to_thread(self._read_barcode, photo)
        if code is None:
            return NO_BARCODE
        text = f"штрихкод {code}"
        if caption and caption.strip():
            text = f"{text}, {caption.strip()}"
        return await self.text(person, text, account)

    async def _turn(self, call: Awaitable[str]) -> str:
        """Ждёт ответ ядра и переводит ошибки в понятные человеку ответы."""
        try:
            answer = await call
        except CoreUnauthorizedError as error:
            log.error("Ядро не приняло токен бота (%s): проверьте core.token в settings.toml", error)
            return CORE_UNAUTHORIZED
        except CoreRejectedError as error:
            log.warning("Ядро отклонило ход: %s", error)
            return CORE_REJECTED
        except CoreUnavailableError as error:
            log.warning("Ядро недоступно: %s", error)
            return CORE_UNAVAILABLE
        return answer if answer.strip() else CORE_EMPTY
