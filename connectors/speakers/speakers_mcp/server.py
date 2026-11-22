"""MCP-сервер speakers: колонки дома — какие есть и какая у них громкость (stdio).

Колонка без названия в вызове — та, с которой сейчас говорят (`_meta.device` вызова от ядра).
"""

from __future__ import annotations

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from speakers_mcp.core_api import CoreApi, CoreUnavailableError, Speaker

STEP = 10  # «погромче» без числа — на столько процентов


def pick_speaker(speakers: list[Speaker], name: str, current: str | None) -> Speaker:
    """Колонка по названию (без учёта регистра, можно начало), иначе текущая, иначе единственная в сети."""
    wanted = name.strip().casefold()
    if wanted:
        found = [s for s in speakers if s.name.casefold() == wanted] or [
            s for s in speakers if s.name.casefold().startswith(wanted) or wanted in s.name.casefold()
        ]
        if len(found) == 1:
            return found[0]
        raise ToolError(f"Нет колонки «{name}». Есть: {', '.join(s.name for s in speakers) or 'никаких'}.")
    by_id = [s for s in speakers if s.id == current]
    online = [s for s in speakers if s.online]
    if by_id:
        return by_id[0]
    if len(online) == 1:
        return online[0]
    raise ToolError(f"Какую колонку? Есть: {', '.join(s.name for s in online) or 'ни одной в сети'}.")


def _current(ctx: Context) -> str | None:
    meta = ctx.request_context.meta
    value = meta.get("device") if meta else None
    return value if isinstance(value, str) and value else None


def build_server(api: CoreApi | None = None) -> MCPServer:
    """Сервер с двумя инструментами; api — клиент ядра (в тестах — поддельный)."""
    core = api or CoreApi()
    server = MCPServer("speakers")

    @server.tool(name="speakers_list", description="Колонки дома: названия, в сети ли и громкость каждой.")
    async def speakers_list() -> str:
        try:
            speakers = await core.speakers()
        except CoreUnavailableError as error:
            raise ToolError(str(error)) from None
        rows = [
            f"{s.name}: {'в сети' if s.online else 'не в сети'}, громкость {s.volume} %" for s in speakers
        ]
        return "; ".join(rows) or "Колонок нет."

    @server.tool(
        name="speaker_volume",
        description=(
            "Громкость колонки: узнать или изменить. percent — сколько поставить (0–100); change — на "
            "сколько изменить (+10 «погромче», -10 «потише»); оба пусты — только узнать. speaker — название "
            "колонки; пусто — та, с которой сейчас говорят."
        ),
    )
    async def speaker_volume(
        ctx: Context, percent: int | None = None, change: int | None = None, speaker: str = ""
    ) -> str:
        try:
            target = pick_speaker(await core.speakers(), speaker, _current(ctx))
            if percent is None and change is None:
                return f"Громкость «{target.name}»: {target.volume} %."
            value = max(0, min(100, percent if percent is not None else target.volume + (change or 0)))
            await core.set_volume(target.id, value)
        except CoreUnavailableError as error:
            raise ToolError(str(error)) from None
        return f"Громкость «{target.name}»: {value} % (было {target.volume} %)."

    return server


def main() -> None:
    """Запуск по stdio (так его запускает ядро)."""
    build_server().run()
