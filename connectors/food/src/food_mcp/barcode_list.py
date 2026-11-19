"""barcode-list.ru: название товара по штрихкоду (сеть, без VPN), кэш на 30 дней.

Сайт отдаёт только название («ВМ Кефир 1% 0,950л»), без калорийности. Запросы поштучные
(один за раз) и не чаще одного в 10 секунд на весь коннектор, как разрешает их robots.txt.
"""

import asyncio
import html
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx

from .off import barcode_key
from .storage import read_text, write_atomic

URL = "https://barcode-list.ru/barcode/RU/%D0%9F%D0%BE%D0%B8%D1%81%D0%BA.htm"
USER_AGENT = "SmartEsp-food/0.1 (home assistant)"
TIMEOUT_S = 5.0
MIN_INTERVAL_S = 10.0
CACHE_TTL = timedelta(days=30)
CACHE_FILE = "barcode_names.json"

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_TITLE_TAIL = re.compile(r"\s*-\s*Штрих-код:.*$", re.S)
_TABLE = re.compile(r'<table[^>]*class="randomBarcodes"[^>]*>(.*?)</table>', re.S | re.I)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.I)
_HEADER_CHARSET = re.compile(r"charset=([\w-]+)", re.I)
_NOT_FOUND = ("не найден", "ничего не найдено")
_DEFAULT_CHARSETS = ("iso-8859-1", "latin-1", "latin1")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_NAME = 120
MAX_PAGE = 1_000_000
MAX_WAIT_S = 6.0  # дольше не ждём: у хаба на вызов инструмента 15 секунд


@dataclass(frozen=True)
class NameResult:
    """Ответ справочника.

    `status`: found — есть название (`name`); missing — страница «такого штрихкода нет»;
    offline — нет сети или сервис недоступен; unknown — пришла страница, которую не удалось
    разобрать (блокировка, капча, изменилась вёрстка); busy — запрос слишком частый.
    В кэш попадают только found и missing.
    """

    status: Literal["found", "missing", "offline", "unknown", "busy"]
    name: str = ""


def decode(content: bytes, content_type: str = "") -> str:
    """Текст страницы: кодировка из заголовка, затем из meta; иначе UTF-8, иначе Windows-1251.

    iso-8859-1 в заголовке — умолчание HTTP, а не настоящее объявление: игнорируется.
    """
    declared = _HEADER_CHARSET.search(content_type)
    meta = _META_CHARSET.search(content[:2048])
    charsets = (declared.group(1) if declared else "", meta.group(1).decode("ascii") if meta else "")
    for charset in charsets:
        if charset and charset.lower() not in _DEFAULT_CHARSETS:
            try:
                return content.decode(charset)
            except (LookupError, UnicodeDecodeError):
                continue
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1251", errors="replace")


def _clean(fragment: str) -> str:
    text = _CONTROL.sub(" ", html.unescape(_TAG.sub(" ", fragment)))
    return " ".join(text.split())[:MAX_NAME]


def parse_page(page: str, code: str) -> NameResult:
    """Разбирает страницу результата для штрихкода `code`.

    Название принимается, только если в таблице результатов есть строка с этим кодом.
    «Не найдено» — только явная страница (таблица без строк и форма поиска, либо
    сообщение «не найден»). Остальное — `unknown`: страница не та, что ожидали.
    """
    title_match = _TITLE.search(page)
    title = _TITLE_TAIL.sub("", _clean(title_match.group(1))) if title_match else ""
    table = _TABLE.search(page)
    if table is None:
        found_not = any(m in page.lower() for m in _NOT_FOUND)
        return NameResult("missing") if found_not else NameResult("unknown")
    key = barcode_key(code)
    rows = [_CELL.findall(r) for r in _ROW.findall(table.group(1))]
    rows = [cells for cells in rows if len(cells) >= 3]
    if not rows:
        return NameResult("missing") if "<form" in page.lower() else NameResult("unknown")
    for cells in rows:
        digits = "".join(c for c in _clean(cells[1]) if c.isdigit())
        row_name = _clean(cells[2])
        if digits and barcode_key(digits) == key and row_name:
            if title.lower() == row_name.lower():
                return NameResult("found", title)
            return NameResult("found", row_name.capitalize() if row_name.isupper() else row_name)
    return NameResult("unknown")


class BarcodeList:
    """Клиент barcode-list.ru; `transport` и `clock` подменяются в тестах (сеть не нужна)."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def lookup(self, code: str) -> NameResult:
        """Название по проверенному штрихкоду.

        Пауза между запросами — 10 с: если ждать не больше 6 с, ждём внутри замка;
        иначе `busy`. Слот тратится и при неудачном запросе (на сайт мы всё же сходили).
        """
        async with self._lock:
            if self._last is not None:
                remaining = MIN_INTERVAL_S - (self._clock() - self._last)
                if remaining > MAX_WAIT_S:
                    return NameResult("busy")
                if remaining > 0:
                    await self._sleep(remaining)
            self._last = self._clock()
            try:
                # Один срок на весь запрос: таймаут httpx ограничивает каждую фазу отдельно.
                async with asyncio.timeout(TIMEOUT_S):
                    async with httpx.AsyncClient(
                        transport=self._transport, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}
                    ) as client:
                        response = await client.get(URL, params={"barcode": code})
                response.raise_for_status()
                page = decode(response.content[:MAX_PAGE], response.headers.get("content-type", ""))
            except (httpx.HTTPError, TimeoutError):
                return NameResult("offline")
        return parse_page(page, code)


def _load(root: Path) -> dict[str, dict[str, str | None]]:
    try:
        data = json.loads(read_text(root / CACHE_FILE) or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def cached(root: Path, code: str, now: datetime) -> NameResult | None:
    """Прошлый ответ из кэша (живёт 30 дней, «не найдено» — тоже); нет или устарел — None."""
    entry = _load(root).get(barcode_key(code))
    try:
        if not isinstance(entry, dict) or now - datetime.fromisoformat(str(entry["time"])) > CACHE_TTL:
            return None
    except (KeyError, ValueError):
        return None
    name = entry.get("name")
    return NameResult("found", name) if name else NameResult("missing")


def remember(root: Path, code: str, result: NameResult, now: datetime) -> None:
    """Кэширует найденное и «не найдено»; сетевые сбои не кэшируются."""
    if result.status not in ("found", "missing"):
        return
    data = _load(root)
    data[barcode_key(code)] = {"name": result.name or None, "time": now.isoformat(timespec="seconds")}
    write_atomic(root / CACHE_FILE, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
