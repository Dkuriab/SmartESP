"""MCP-сервер web: поиск DuckDuckGo и чтение страниц (stdio)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from web_mcp.fetch import TIMEOUT, PageError, read_page
from web_mcp.guard import make_guarded_transport
from web_mcp.limits import RateLimiter
from web_mcp.search import SearchBlocked, SearchUnavailable, search
from web_mcp.speech import page_answer, search_answer

TIMEOUT_SECONDS = 8.0
SEARCH_PER_MINUTE = 10
READ_PER_MINUTE = 20
# DuckDuckGo показал капчу — столько секунд не ходим в поиск
BLOCK_PAUSE_SECONDS = 300.0
MAX_QUERY_CHARS = 300
USER_AGENT = "SmartEsp-web/0.1"
# часть сайтов не отдаёт страницы неизвестным программам — представляемся как совместимый браузер
READER_AGENT = "Mozilla/5.0 (compatible; SmartEsp-web/0.1)"

SEARCH_UNAVAILABLE = "Поиск сейчас недоступен."
SEARCH_PAUSED = "Поиск сейчас недоступен, попробуйте через несколько минут."
TOO_OFTEN = "Слишком много запросов в интернет подряд. Попробуйте через минуту."
FAILURE = "Не получилось сходить в интернет."

SEARCH_DESCRIPTION = (
    "Поиск в интернете (DuckDuckGo). Вызывайте для свежих фактов, новостей, цен, курсов, "
    "расписаний и всего, чего вы не знаете наверняка. query — запрос, как в поисковике: "
    "«курс доллара сегодня». Отвечайте коротко своими словами и называйте сайт-источник "
    "(домен), адреса вслух не читайте."
)
READ_DESCRIPTION = (
    "Прочитать текст страницы по ссылке (без JavaScript, до 8000 символов). Вызывайте, "
    "когда человек дал ссылку или чтобы прочитать страницу, найденную через web_search. "
    "url — полный адрес http или https. Пересказывайте коротко и называйте сайт (домен)."
)

log = logging.getLogger("web_mcp")


async def _guarded[T](action: Callable[[], Awaitable[T]]) -> T:
    """Любая неожиданная ошибка превращается в честный ответ; подробности — в лог."""
    try:
        return await action()
    except ToolError:
        raise
    except Exception:
        log.exception("web tool failed")
        raise ToolError(FAILURE) from None


class _Web:
    """Клиенты и пределы частоты; транспорт и часы подменяются в тестах."""

    def __init__(
        self, transport: httpx.AsyncBaseTransport | None, clock: Callable[[], float], timeout: float
    ) -> None:
        self._transport = transport
        self._timeout = timeout
        self.searches = RateLimiter(SEARCH_PER_MINUTE, 60.0, clock)
        self.reads = RateLimiter(READ_PER_MINUTE, 60.0, clock)

    async def search(self, query: str) -> CallToolResult:
        if self.searches.paused():
            raise ToolError(SEARCH_PAUSED)
        if not self.searches.allow():
            raise ToolError(TOO_OFTEN)
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.5"}
        try:
            async with (
                asyncio.timeout(self._timeout),
                httpx.AsyncClient(
                    timeout=self._timeout, headers=headers, transport=self._transport
                ) as client,
            ):
                results = await search(client, query)
        except SearchBlocked as error:
            log.warning("search blocked: %s", error)
            self.searches.pause(BLOCK_PAUSE_SECONDS)
            raise ToolError(SEARCH_UNAVAILABLE) from None
        except (SearchUnavailable, TimeoutError) as error:
            log.warning("search failed: %r", error)
            raise ToolError(SEARCH_UNAVAILABLE) from None
        text = search_answer(query, results) if results else f"Ничего не нашлось по запросу «{query}»."
        structured = {"results": [asdict(result) for result in results]}
        return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=structured)

    async def read(self, url: str) -> str:
        if not self.reads.allow():
            raise ToolError(TOO_OFTEN)
        transport = self._transport or make_guarded_transport()
        headers = {"User-Agent": READER_AGENT, "Accept-Language": "ru,en;q=0.5"}
        try:
            async with (
                asyncio.timeout(self._timeout),
                httpx.AsyncClient(
                    timeout=self._timeout, headers=headers, transport=transport, trust_env=False
                ) as client,
            ):
                page = await read_page(client, url)
        except PageError as error:
            log.warning("read %s failed: %s", url, error)
            raise ToolError(str(error)) from None
        except TimeoutError:
            raise ToolError(TIMEOUT) from None
        return page_answer(page.url, page.title, page.text, page.truncated)


def build_server(
    transport: httpx.AsyncBaseTransport | None = None,
    *,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = TIMEOUT_SECONDS,
) -> MCPServer:
    """Собирает сервер с web_search и web_read. transport, clock, timeout — для тестов.

    Без transport поиск идёт обычным клиентом, а чтение — через защищённый
    транспорт: подключение только к адресам интернета (см. guard).
    """
    web = _Web(transport, clock, timeout)
    server = MCPServer("web")

    @server.tool(name="web_search", description=SEARCH_DESCRIPTION)
    async def web_search(query: str) -> CallToolResult:
        query = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not query:
            raise ToolError("Не понял, что искать.")
        return await _guarded(lambda: web.search(query))

    @server.tool(name="web_read", description=READ_DESCRIPTION)
    async def web_read(url: str) -> str:
        return await _guarded(lambda: web.read(url.strip()))

    return server


def main() -> None:
    """Точка входа `web-mcp`: запуск по stdio. Данных не хранит."""
    build_server().run("stdio")
