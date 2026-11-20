"""Поиск DuckDuckGo без ключа: HTML-выдача html.duckduckgo.com, регион — Россия."""

from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser, LexborNode

SEARCH_URL = "https://html.duckduckgo.com/html/"
REGION = "ru-ru"
MAX_RESULTS = 5
# признаки страницы-проверки «вы не робот?»
_CAPTCHA_MARKS = ("anomaly-modal", "challenge-form", "bots use DuckDuckGo")


class SearchUnavailable(Exception):
    """Поиск не ответил или ответил не выдачей."""


class SearchBlocked(SearchUnavailable):
    """DuckDuckGo просит пройти проверку или ограничил частоту — стоит подождать."""


@dataclass(frozen=True)
class SearchResult:
    """Один результат выдачи."""

    title: str
    url: str
    snippet: str


def looks_blocked(status: int, html: str) -> bool:
    """True — вместо выдачи капча или отказ по частоте (202, 403, 429)."""
    if status in (202, 403, 429):
        return True
    return any(mark in html for mark in _CAPTCHA_MARKS)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _real_url(href: str) -> str | None:
    """Адрес результата: ссылки-переходы //duckduckgo.com/l/?uddg=… раскрываются."""
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if parts.netloc.endswith("duckduckgo.com"):
        if parts.path != "/l/":
            return None  # реклама и служебные ссылки
        target = parse_qs(parts.query).get("uddg")
        if not target:
            return None
        href = target[0]
        parts = urlsplit(href)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return href


def _parse_one(node: LexborNode) -> SearchResult | None:
    link = node.css_first("a.result__a")
    if link is None:
        return None
    url = _real_url(link.attributes.get("href") or "")
    if url is None:
        return None
    snippet = node.css_first(".result__snippet")
    return SearchResult(
        title=_clean(link.text()),
        url=url,
        snippet=_clean(snippet.text()) if snippet is not None else "",
    )


def parse_results(html: str, limit: int = MAX_RESULTS) -> list[SearchResult]:
    """Первые limit результатов выдачи без рекламы и битых ссылок."""
    if not html:
        return []
    results: list[SearchResult] = []
    for node in LexborHTMLParser(html).css("div.result"):
        if "result--ad" in (node.attributes.get("class") or ""):
            continue
        result = _parse_one(node)
        if result is not None:
            results.append(result)
        if len(results) >= limit:
            break
    return results


async def search(client: httpx.AsyncClient, query: str) -> list[SearchResult]:
    """Запрос к DuckDuckGo (POST, как форма на сайте). Сбой — SearchUnavailable/SearchBlocked."""
    try:
        response = await client.post(SEARCH_URL, data={"q": query, "kl": REGION})
    except httpx.HTTPError as error:
        raise SearchUnavailable(str(error)) from error
    text = response.text
    if looks_blocked(response.status_code, text):
        raise SearchBlocked(f"status {response.status_code}")
    if response.status_code != 200:
        raise SearchUnavailable(f"status {response.status_code}")
    return parse_results(text)
