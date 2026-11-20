"""Текст страницы без JavaScript: кодировка, заголовок и главное содержимое.

Упрощённый «режим чтения»: выбрасываются скрипты, стили, меню, формы; из
article/main/[role=main] берётся самый длинный, если в нём достаточно текста,
иначе — всё тело страницы без шапки и подвала. Блоки разделяются переводом строки.
"""

import codecs
import re
from dataclasses import dataclass

from selectolax.lexbor import LexborHTMLParser, LexborNode

MIN_MAIN_CHARS = 200
# метка границы блока: переводы строк в самом HTML — обычные пробелы
_BREAK = "\ue000"
_JUNK = [
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "object",
    "embed",
    "nav",
    "aside",
    "form",
    "button",
    "select",
    "dialog",
]
_PAGE_FRAME = ["header", "footer"]
_BLOCKS = (
    "p, div, section, article, main, ul, ol, li, dl, dt, dd, h1, h2, h3, h4, h5, h6, "
    "blockquote, pre, table, tr, figcaption, header, footer"
)
_HIDDEN = '[hidden], [aria-hidden="true"], [style*="display:none"], [style*="display: none"]'
# список, где почти весь текст — ссылки (языки, меню, теги), — не содержимое
LINK_SHARE = 0.8
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:\-]+)""", re.IGNORECASE)


@dataclass(frozen=True)
class Extracted:
    """Заголовок и текст страницы (строки через перевод строки, без пустых)."""

    title: str
    text: str


def plain_text(text: str) -> str:
    """Пробелы внутри строк схлопываются, пустые строки убираются."""
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    try:
        return codecs.lookup(name.strip()).name
    except LookupError:
        return None


def decode(body: bytes, charset: str | None) -> str:
    """Байты в текст: кодировка из заголовка, иначе из <meta>, иначе UTF-8, иначе cp1251."""
    meta = _META_CHARSET.search(body[:4096])
    for name in (charset, meta.group(1).decode("ascii", "ignore") if meta else None):
        codec = _codec(name)
        if codec:
            return body.decode(codec, errors="replace")
    try:
        # final=False: обрезанный по пределу размера хвост не считается ошибкой
        return codecs.getincrementaldecoder("utf-8")().decode(body, final=False)
    except UnicodeDecodeError:
        return body.decode("cp1251", errors="replace")


def _title(tree: LexborHTMLParser) -> str:
    og = tree.css_first('meta[property="og:title"]')
    if og is not None and (og.attributes.get("content") or "").strip():
        return " ".join((og.attributes.get("content") or "").split())
    for selector in ("title", "h1"):
        node = tree.css_first(selector)
        if node is not None and node.text().strip():
            return " ".join(node.text().split())
    return ""


def _letters(text: str) -> int:
    return len("".join(text.split()))


def _link_list(node: LexborNode) -> bool:
    total = _letters(node.text())
    if total == 0 or len(node.css("li")) < 3:
        return False
    return sum(_letters(link.text()) for link in node.css("a")) / total >= LINK_SHARE


def _drop_noise(tree: LexborHTMLParser) -> None:
    """Убирает скрытые блоки и списки ссылок; вложенные удаляются вместе с внешним."""
    marked = {node.mem_id: node for node in tree.css(_HIDDEN)}
    marked.update((node.mem_id, node) for node in tree.css("ul, ol") if _link_list(node))
    top: list[LexborNode] = []
    for node in marked.values():
        parent = node.parent
        while parent is not None and parent.mem_id not in marked:
            parent = parent.parent
        if parent is None:
            top.append(node)
    for node in top:
        node.decompose()


def _main(tree: LexborHTMLParser) -> LexborNode | None:
    """Самый длинный article/main с достаточным текстом, иначе тело без шапки и подвала."""
    candidates = tree.css("article, main, [role=main]")
    best = max(candidates, key=lambda node: len(node.text()), default=None)
    if best is not None and len(plain_text(best.text())) >= MIN_MAIN_CHARS:
        best.strip_tags(["footer"], recursive=True)
        return best
    body = tree.body
    if body is not None:
        body.strip_tags(_PAGE_FRAME, recursive=True)
    return body


def extract(html: str) -> Extracted:
    """Заголовок и главный текст HTML-страницы."""
    tree = LexborHTMLParser(html)
    title = _title(tree)
    tree.strip_tags(_JUNK, recursive=True)
    _drop_noise(tree)
    root = _main(tree)
    if root is None:
        return Extracted(title, "")
    for node in root.css(_BLOCKS):
        node.insert_before(_BREAK)
        node.insert_after(_BREAK)
    for node in root.css("br"):
        node.insert_after(_BREAK)
    lines = (" ".join(part.split()) for part in root.text().split(_BREAK))
    return Extracted(title, "\n".join(line for line in lines if line))
