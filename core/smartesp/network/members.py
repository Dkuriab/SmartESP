"""Вспомогательное для участников сети: их инструменты и прогрев."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from smartesp.contracts import ToolSpec, WarmsUp

from .rules import Target, delegate_tool

if TYPE_CHECKING:
    from .network import Member

_log = logging.getLogger("smartesp.network.network")  # журнал сети: прогрев — её часть


def member_tools(
    member: Member, offered: tuple[Target, ...], extra_tools: tuple[ToolSpec, ...]
) -> tuple[ToolSpec, ...]:
    """Инструменты участника: без tools_ok — никаких; иначе extra_tools, свои и delegate, если есть цели."""
    if not member.tools_ok:
        return ()
    own = (*extra_tools, *member.tools)
    return (*own, delegate_tool(offered)) if offered else own


async def warm(member_id: str, executor: WarmsUp, timeout_s: float) -> str | None:
    """Прогревает одного участника не дольше timeout_s; None — успех, иначе текст ошибки."""
    try:
        async with asyncio.timeout(timeout_s):
            await executor.warm_up()
    except TimeoutError:
        error = f"не прогрелся за {timeout_s:g} с"
    except Exception as exc:  # noqa: BLE001 — прогрев участника не должен ломать связку
        error = str(exc) or type(exc).__name__
    else:
        return None
    _log.warning("Исполнитель «%s» не прогрелся: %s", member_id, error)
    return error
