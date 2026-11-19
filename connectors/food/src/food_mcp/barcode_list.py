"""barcode-list.ru: название товара по штрихкоду (сеть, без VPN), кэш на 30 дней.

Сайт отдаёт только название («ВМ Кефир 1% 0,950л»), без калорийности. Запросы поштучные
(один за раз) и не чаще одного в 10 секунд на весь коннектор, как разрешает их robots.txt.
"""

import asyncio
import html
import json
import re
import time
from collections.abc import Callable
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


@dataclass(frozen=True)
class NameResult:
    """Ответ справочника.

    `status`: found — есть название (`name`); missing — такого штрихкода нет;
    offline — сеть или сервис недоступны; busy — запрос был слишком недавно (не чаще раза в 10 с).
    """

    status: Literal["found", "missing", "offline", "busy"]
    name: str = ""


def decode(content: bytes, content_type: str = "") -> str:
    """Текст страницы: кодировка из заголовка, затем из meta; иначе UTF-8, иначе Windows-1251."""
    declared = _HEADER_CHARSET.search(content_type)
    meta = _META_CHARSET.search(content[:2048])
    for charset in (declared.group(1) if declared else "", meta.group(1).decode("ascii") if meta else ""):
        if charset:
            try:
                return content.decode(charset)
            except (LookupError, UnicodeDecodeError):
                continue
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1251", errors="replace")


def _clean(fragment: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def parse_name(page: str) -> str:
    """Название товара со страницы результата; пустая строка — на странице ничего нет.

    Сначала первая строка таблицы названий (лучший рейтинг), затем заголовок страницы.
    Заголовок красивее (регистр), поэтому он берётся, если совпадает со строкой таблицы.
    """
    title_match = _TITLE.search(page)
    title = _TITLE_TAIL.sub("", _clean(title_match.group(1))) if title_match else ""
    if any(m in title.lower() for m in _NOT_FOUND):
        return ""
    table = _TABLE.search(page)
    row_name = ""
    if table:
        for row in _ROW.findall(table.group(1)):
            cells = _CELL.findall(row)
            if len(cells) >= 3:
                row_name = _clean(cells[2])
                break
    if row_name and title.lower() != row_name.lower():
        return row_name.capitalize() if row_name.isupper() else row_name
    return title or row_name


class BarcodeList:
    """Клиент barcode-list.ru; `transport` и `clock` подменяются в тестах (сеть не нужна)."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self._lock = asyncio.Lock()
        self._last: float | None = None

    async def lookup(self, code: str) -> NameResult:
        """Название по проверенному штрихкоду. Слишком частый запрос — `busy`, без ожидания."""
        async with self._lock:
            now = self._clock()
            if self._last is not None and now - self._last < MIN_INTERVAL_S:
                return NameResult("busy")
            self._last = now
            try:
                # Один срок на весь запрос: таймаут httpx ограничивает каждую фазу отдельно.
                async with asyncio.timeout(TIMEOUT_S):
                    async with httpx.AsyncClient(
                        transport=self._transport, timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}
                    ) as client:
                        response = await client.get(URL, params={"barcode": code})
                if response.status_code == 404:
                    return NameResult("missing")
                response.raise_for_status()
                page = decode(response.content, response.headers.get("content-type", ""))
            except (httpx.HTTPError, TimeoutError):
                return NameResult("offline")
        name = parse_name(page)
        return NameResult("found", name) if name else NameResult("missing")


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
