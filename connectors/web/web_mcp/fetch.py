"""Чтение страницы: до 3 перенаправлений с проверкой каждого адреса, до 2 МБ, только текст."""

from dataclasses import dataclass

import httpx

from web_mcp.extract import decode, extract, plain_text
from web_mcp.guard import BadUrl, BlockedAddress, check_url
from web_mcp.speech import shorten

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TEXT_CHARS = 8000
_TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")

ONLY_HTTP = "Открываю только ссылки http и https."
LOCAL_ADDRESS = "Это адрес домашней сети или самого компьютера — такие страницы не открываю."
TIMEOUT = "Сайт не ответил вовремя."
FAILED = "Не получилось открыть страницу."
TOO_MANY_REDIRECTS = "Слишком много перенаправлений, страницу не открыть."
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


async def _open(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET с ручными перенаправлениями: каждый новый адрес проходит check_url."""
    current = check_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        response = await client.send(client.build_request("GET", current), stream=True)
        if not response.is_redirect:
            return response
        await response.aclose()
        try:
            target = current.join(response.headers["location"])
        except httpx.InvalidURL as error:
            raise BadUrl(str(error)) from error
        current = check_url(str(target))
    raise PageError(TOO_MANY_REDIRECTS)


def _content_type(response: httpx.Response) -> tuple[str, str | None]:
    """Тип содержимого и кодировка из заголовка; без заголовка считаем HTML."""
    media, _, params = response.headers.get("content-type", "text/html").partition(";")
    charset = None
    for param in params.split(";"):
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset":
            charset = value.strip().strip("\"'")
    return media.strip().lower(), charset


async def _body(response: httpx.Response) -> tuple[bytes, bool]:
    """Тело ответа не больше MAX_BYTES (после распаковки); True — дальше не читали."""
    data = bytearray()
    async for chunk in response.aiter_bytes():
        data += chunk
        if len(data) >= MAX_BYTES:
            return bytes(data[:MAX_BYTES]), True
    return bytes(data), False


async def _download(response: httpx.Response) -> tuple[bytes, str, str | None, bool]:
    if response.status_code >= 400:
        raise PageError(f"Сайт ответил ошибкой {response.status_code}.")
    media, charset = _content_type(response)
    if media not in _TEXT_TYPES:
        raise PageError(f"Это не страница с текстом, а файл ({media}) — его не прочитать.")
    body, cut = await _body(response)
    return body, media, charset, cut


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


async def read_page(client: httpx.AsyncClient, url: str) -> Page:
    """Читает страницу. Любой отказ — PageError с готовой фразой."""
    try:
        response = await _open(client, url)
        try:
            body, media, charset, cut = await _download(response)
        finally:
            await response.aclose()
    except BadUrl:
        raise PageError(ONLY_HTTP) from None
    except BlockedAddress:
        raise PageError(LOCAL_ADDRESS) from None
    except httpx.TimeoutException:
        raise PageError(TIMEOUT) from None
    except httpx.HTTPError:
        raise PageError(FAILED) from None
    return _page(str(response.url), body, media, charset, cut)
