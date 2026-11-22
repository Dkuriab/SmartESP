"""Точка входа `uv run telegram-bot` — связка: настройки → клиент ядра → бот → long polling."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from aiogram import Bot

from .assistant import Assistant
from .bot import build_dispatcher
from .core_client import CoreClient
from .notices import StrangerNotices
from .settings import Settings, SettingsError, load_settings

DEFAULT_SETTINGS = Path(__file__).resolve().parent.parent / "settings.toml"

log = logging.getLogger(__name__)


async def run(settings: Settings) -> None:
    """Запускает бота: исходящий long polling, без вебхуков и открытых портов."""
    async with CoreClient(settings.core_url, settings.core_token) as core:
        strangers = StrangerNotices() if settings.managed else None  # от ядра: «Добавить» в приложении
        dispatcher = build_dispatcher(Assistant(core, settings.users), strangers)
        bot = Bot(settings.bot_token)
        log.info("Бот запущен: ядро %s, допущено людей: %d", settings.core_url, len(settings.users))
        # у aiogram в сигнатуре start_polling есть тип без аннотации — strict ругается на библиотеку
        await dispatcher.start_polling(  # pyright: ignore[reportUnknownMemberType]
            bot, allowed_updates=dispatcher.resolve_used_update_types()
        )


def main(argv: Sequence[str] | None = None) -> None:
    """Разбирает аргументы, читает настройки и запускает бота; без настроек — выход с кодом 2."""
    parser = argparse.ArgumentParser(prog="telegram-bot", description="Telegram-бот SmartESP")
    parser.add_argument(
        "--settings",
        type=Path,
        default=DEFAULT_SETTINGS,
        help=f"файл настроек (по умолчанию {DEFAULT_SETTINGS})",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = load_settings(args.settings)
    except SettingsError as error:
        print(f"telegram-bot: {error}", file=sys.stderr)
        raise SystemExit(2) from None
    asyncio.run(run(settings))
