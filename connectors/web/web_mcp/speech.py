"""Тексты ответов: источник называется по домену, адреса — только в списке ссылок."""

from collections.abc import Sequence

import httpx

from web_mcp.search import SearchResult

BEST_COUNT = 3
SNIPPET_CHARS = 240
TITLE_CHARS = 150


def domain(url: str) -> str:
    """Домен для озвучки: без www, кириллические домены — кириллицей («сайт.рф»)."""
    try:
        host = httpx.URL(url).host
    except httpx.InvalidURL:
        return url
    if host.startswith("www."):
        host = host[4:]
    return host


def shorten(text: str, limit: int) -> str:
    """Обрезает по границе слова и ставит «…»; короткий текст не меняется."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:—-") + "…"


def _best(results: Sequence[SearchResult]) -> list[SearchResult]:
    """2–3 лучших для пересказа: с текстом, сначала с разных сайтов, в порядке выдачи."""
    pool = [r for r in results if r.snippet] or list(results)
    picked: list[SearchResult] = []
    seen: set[str] = set()
    for result in pool:
        if domain(result.url) not in seen and len(picked) < BEST_COUNT:
            picked.append(result)
            seen.add(domain(result.url))
    for result in pool:
        if len(picked) >= BEST_COUNT:
            break
        if result not in picked:
            picked.append(result)
    return sorted(picked, key=pool.index)


def search_answer(query: str, results: Sequence[SearchResult]) -> str:
    """Главное — «домен: сниппет» для пересказа; ниже все результаты с адресами для web_read."""
    lines = [f"По запросу «{query}» нашлось:"]
    for result in _best(results):
        text = result.snippet or result.title
        lines.append(f"{domain(result.url)}: {shorten(text, SNIPPET_CHARS)}")
    lines.append("Все результаты (открыть страницу — web_read с адресом):")
    for number, result in enumerate(results, 1):
        title = shorten(result.title, TITLE_CHARS)
        lines.append(f"{number}. {title} — {domain(result.url)} — {result.url}")
    return "\n".join(lines)


def page_answer(url: str, title: str, text: str, truncated: bool) -> str:
    """Источник и заголовок, затем текст страницы; обрезанный текст помечается."""
    head = f"Страница с сайта {domain(url)}"
    head += f": «{shorten(title, TITLE_CHARS)}»." if title else "."
    tail = "\n(Дальше текст обрезан.)" if truncated else ""
    return f"{head}\n\n{text}{tail}"
