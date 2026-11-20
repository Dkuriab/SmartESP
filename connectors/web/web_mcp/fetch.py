"""Чтение страницы: до 3 перенаправлений с проверкой каждого адреса, до 2 МБ, только текст."""

from dataclasses import dataclass

import httpcore
import httpx

from web_mcp.body import BadBody, UnsupportedEncoding
from web_mcp.extract import decode, extract, plain_text
from web_mcp.guard import BadUrl, BlockedAddress, check_url
from web_mcp.net import NETWORK_ERRORS, Headers, Reply, is_redirect, request
from web_mcp.speech import shorten

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TEXT_CHARS = 8000
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
# часть сайтов не отдаёт страницы неизвестным программам — представляемся совместимым браузером
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SmartEsp-web/0.1)",
    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
    "Accept-Language": "ru,en;q=0.5",
}

ONLY_HTTP = "Открываю только ссылки http и https."
LOCAL_ADDRESS = "Это адрес домашней сети или самого компьютера — такие страницы не открываю."
TIMEOUT = "Сайт не ответил вовремя."
FAILED = "Не получилось открыть страницу."
TOO_MANY_REDIRECTS = "Слишком много перенаправлений, страницу не открыть."
UNSUPPORTED_ENCODING = "Сайт прислал страницу в сжатом виде, который я не читаю."
NO_TEXT = "На странице нет текста, который можно прочитать без JavaScript."


class PageError(Exception):
    """Страницу не прочитать; текст ошибки — готовая фраза для ответа."""


@dataclass(frozen=True)
class Page:
    """Прочитанная страница: итоговый адрес, заголовок, текст (не длиннее TEXT_CHARS)."""

    url: str
    title: str
    text: str
    truncated: bool


def first_url(url: str) -> httpx.URL:
    """Проверенная ссылка; плохая или локальная — PageError (до похода в сеть)."""
    try:
        return check_url(url)
    except BadUrl:
        raise PageError(ONLY_HTTP) from None
    except BlockedAddress:
        raise PageError(LOCAL_ADDRESS) from None


def _content_type(headers: Headers) -> tuple[str, str | None]:
    """Тип содержимого и кодировка из заголовка; без заголовка считаем HTML."""
    media, _, params = headers.get("content-type", "text/html").partition(";")
    charset = None
    for param in params.split(";"):
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset":
            charset = value.strip().strip("\"'")
    return media.strip().lower(), charset


def _wants_body(status: int, headers: Headers) -> bool:
    """Тело нужно только у страницы с текстом; перенаправление и ошибки — без тела."""
    if is_redirect(status, headers):
        return False
    if status >= 400:
        raise PageError(f"Сайт ответил ошибкой {status}.")
    media, _ = _content_type(headers)
    if media not in _TEXT_TYPES:
        raise PageError(f"Это не страница с текстом, а файл ({media}) — его не прочитать.")
    return True


async def _get(pool: httpcore.AsyncConnectionPool, url: httpx.URL, timeout: float) -> tuple[httpx.URL, Reply]:
    """GET с ручными перенаправлениями: каждый новый адрес проходит check_url."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        reply = await request(
            pool, "GET", current, headers=HEADERS, timeout=timeout, limit=MAX_BYTES, wants_body=_wants_body
        )
        if not is_redirect(reply.status, reply.headers):
            return current, reply
        try:
            target = current.join(reply.headers["location"])
        except httpx.InvalidURL as error:
            raise BadUrl(str(error)) from error
        current = check_url(str(target))
    raise PageError(TOO_MANY_REDIRECTS)


def _page(url: str, body: bytes, media: str, charset: str | None, cut: bool) -> Page:
    text = decode(body, charset)
    if media == "text/plain":
        title, text = "", plain_text(text)
    else:
        extracted = extract(text)
        title, text = extracted.title, extracted.text
    if not text:
        raise PageError(NO_TEXT)
    long = len(text) > TEXT_CHARS
    return Page(url, title, shorten(text, TEXT_CHARS) if long else text, cut or long)


async def read_page(pool: httpcore.AsyncConnectionPool, url: httpx.URL, timeout: float) -> Page:
    """Читает страницу (url — из first_url). Любой отказ — PageError с готовой фразой."""
    try:
        final, reply = await _get(pool, url, timeout)
    except BadUrl:
        raise PageError(ONLY_HTTP) from None
    except BlockedAddress:
        raise PageError(LOCAL_ADDRESS) from None
    except UnsupportedEncoding:
        raise PageError(UNSUPPORTED_ENCODING) from None
    except httpcore.TimeoutException:
        raise PageError(TIMEOUT) from None
    except (*NETWORK_ERRORS, BadBody):
        raise PageError(FAILED) from None
    media, charset = _content_type(reply.headers)
    return _page(str(final), reply.body, media, charset, reply.cut)
