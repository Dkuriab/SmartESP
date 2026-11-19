"""Перевод ответов и уведомлений коннектора: результат вызова, журнал, объявления."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from mcp import types

from smartesp.contracts import ToolResult

from .specs import AnnounceHandler

logger = logging.getLogger("smartesp.tools")

ANNOUNCE_LOGGER = "smartesp"  # имя журнала MCP, в котором коннектор шлёт объявления
ANNOUNCE_TYPE = "announce"

# уровни журнала MCP → уровни журнала ядра
_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "notice": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "alert": logging.CRITICAL,
    "emergency": logging.CRITICAL,
}


def tool_result(result: types.CallToolResult) -> ToolResult:
    """Переводит ответ MCP-инструмента в ToolResult: текстовые части через перевод строки.

    Нет текста — структурный ответ в JSON, а если нет и его — короткое «Готово.»/«Ошибка инструмента.».
    """
    texts = [part.text for part in result.content if isinstance(part, types.TextContent)]
    text = "\n".join(texts).strip()
    if not text and result.structured_content is not None:
        text = json.dumps(result.structured_content, ensure_ascii=False)
    if not text:
        text = "Ошибка инструмента." if result.is_error else "Готово."
    return ToolResult(text=text, is_error=bool(result.is_error))


def handle_log(
    params: types.LoggingMessageNotificationParams,
    connector_id: str,
    on_announce: AnnounceHandler | None,
) -> None:
    """Разбирает уведомление журнала коннектора.

    Объявление (logger «smartesp», data.type «announce») уходит в on_announce,
    остальное — в журнал ядра с тем же уровнем. Не бросает исключений.
    """
    fields = _announce_fields(params)
    if fields is not None:
        _announce(fields, connector_id, on_announce)
        return
    level = _LEVELS.get(params.level, logging.INFO)
    logger.log(level, "Коннектор %s [%s]: %s", connector_id, params.logger or "-", params.data)


def _announce_fields(params: types.LoggingMessageNotificationParams) -> dict[str, Any] | None:
    """Поля объявления, если уведомление — объявление; иначе None."""
    data: object = params.data
    if params.logger != ANNOUNCE_LOGGER or not isinstance(data, dict):
        return None
    fields = cast(dict[str, Any], data)
    return fields if fields.get("type") == ANNOUNCE_TYPE else None


def _announce(fields: dict[str, Any], connector_id: str, on_announce: AnnounceHandler | None) -> None:
    """Проверяет поля объявления и передаёт его on_announce; ошибки обработчика — в журнал."""
    text = fields.get("text")
    person = fields.get("person")
    if not isinstance(text, str) or not text.strip() or not (person is None or isinstance(person, str)):
        logger.warning("Коннектор %s: неверное объявление %r", connector_id, fields)
        return
    if on_announce is None:
        logger.info("Коннектор %s: объявление без получателя: %s", connector_id, text)
        return
    try:
        on_announce(text, person, connector_id)
    except Exception:
        logger.exception("Коннектор %s: обработчик объявления упал", connector_id)
