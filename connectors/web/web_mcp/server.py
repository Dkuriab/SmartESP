"""MCP-сервер web: поиск DuckDuckGo и чтение страниц (stdio)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict

import httpcore
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from web_mcp.backend import (
    AddressProvider,
    GuardedBackend,
    OwnAddresses,
    Resolver,
    interface_addresses,
    system_resolve,
)
from web_mcp.fetch import TIMEOUT, PageError, first_url, read_page
from web_mcp.limits import RateLimiter
from web_mcp.search import SearchBlocked, SearchUnavailable, search
from web_mcp.speech import page_answer, search_answer

TIMEOUT_SECONDS = 8.0
SEARCH_PER_MINUTE = 10
READ_PER_MINUTE = 20
# DuckDuckGo показал капчу — столько секунд не ходим в поиск
BLOCK_PAUSE_SECONDS = 300.0
MAX_QUERY_CHARS = 300

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
    """Сетевой слой с защитой и пределы частоты; DNS, сокеты и часы подменяются в тестах."""

    def __init__(
        self,
        resolve: Resolver,
        backend: httpcore.AsyncNetworkBackend | None,
        own: OwnAddresses,
        clock: Callable[[], float],
        timeout: float,
    ) -> None:
        self._resolve = resolve
        self._backend = backend
        self._own = own
        self._timeout = timeout
        self.searches = RateLimiter(SEARCH_PER_MINUTE, 60.0, clock)
        self.reads = RateLimiter(READ_PER_MINUTE, 60.0, clock)

    def _pool(self) -> httpcore.AsyncConnectionPool:
        """Пул соединений только через GuardedBackend: адреса проверяются при каждом подключении."""
        guarded = GuardedBackend(self._resolve, self._backend, self._own)
        return httpcore.AsyncConnectionPool(network_backend=guarded)

    async def search(self, query: str) -> CallToolResult:
        if self.searches.paused():
            raise ToolError(SEARCH_PAUSED)
        if not self.searches.allow():
            raise ToolError(TOO_OFTEN)
        try:
            async with asyncio.timeout(self._timeout), self._pool() as pool:
                results = await search(pool, query, self._timeout)
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
        try:
            checked = first_url(url)
            if not self.reads.allow():
                raise ToolError(TOO_OFTEN)
            async with asyncio.timeout(self._timeout), self._pool() as pool:
                page = await read_page(pool, checked, self._timeout)
        except PageError as error:
            log.warning("read %s failed: %s", url, error)
            raise ToolError(str(error)) from None
        except TimeoutError:
            raise ToolError(TIMEOUT) from None
        return page_answer(page.url, page.title, page.text, page.truncated)


def build_server(
    *,
    resolve: Resolver = system_resolve,
    backend: httpcore.AsyncNetworkBackend | None = None,
    own_addresses: AddressProvider = interface_addresses,
    clock: Callable[[], float] = time.monotonic,
    timeout: float = TIMEOUT_SECONDS,
) -> MCPServer:
    """Собирает сервер с web_search и web_read. Параметры — для тестов.

    resolve — DNS, backend — сокеты под GuardedBackend (по умолчанию настоящие),
    own_addresses — адреса самого компьютера (по умолчанию — интерфейсы).
    Защита адресов работает всегда: подменяются только DNS и сокеты под ней.
    """
    web = _Web(resolve, backend, OwnAddresses(own_addresses, clock), clock, timeout)
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
