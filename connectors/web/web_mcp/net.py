"""Один HTTP-запрос через httpcore: сырые байты, своя распаковка, предел размера.

httpcore — публичный API для своего сетевого слоя (GuardedBackend) и сырого тела;
httpx здесь только разбирает ссылки. Перенаправления не выполняются — их
проходит вызывающий, проверяя каждый адрес.
"""

from collections.abc import Callable
from dataclasses import dataclass

import httpcore
import httpx

from web_mcp.body import read_body

Headers = dict[str, str]
REDIRECT_CODES = (301, 302, 303, 307, 308)
ACCEPT_ENCODING = "gzip, deflate"
# сетевые сбои httpcore (таймауты — отдельно, httpcore.TimeoutException)
NETWORK_ERRORS = (httpcore.NetworkError, httpcore.ProtocolError, httpcore.UnsupportedProtocol)


@dataclass(frozen=True)
class Reply:
    """Ответ: код, заголовки (имена в нижнем регистре), тело и признак обрезки."""

    status: int
    headers: Headers
    body: bytes
    cut: bool


def _headers(raw: list[tuple[bytes, bytes]]) -> Headers:
    """Повторяющиеся заголовки склеиваются через запятую, как велит HTTP."""
    result: Headers = {}
    for name, value in raw:
        key = name.decode("latin-1").lower()
        text = value.decode("latin-1").strip()
        result[key] = f"{result[key]}, {text}" if key in result else text
    return result


def is_redirect(status: int, headers: Headers) -> bool:
    """Перенаправление с адресом в Location."""
    return status in REDIRECT_CODES and bool(headers.get("location"))


async def request(
    pool: httpcore.AsyncConnectionPool,
    method: str,
    url: httpx.URL,
    *,
    headers: Headers,
    timeout: float,
    limit: int,
    content: bytes | None = None,
    wants_body: Callable[[int, Headers], bool] = lambda status, headers: True,
) -> Reply:
    """Отправляет запрос; тело читается, только если wants_body(код, заголовки) вернул True.

    Ошибки: httpcore.TimeoutException, NETWORK_ERRORS, BlockedAddress (из сетевого слоя),
    UnsupportedEncoding/BadBody (тело); wants_body может бросить своё.
    """
    target = httpcore.URL(scheme=url.raw_scheme, host=url.raw_host, port=url.port, target=url.raw_path)
    sent = {"Host": url.netloc.decode("ascii"), **headers}
    sent["Accept-Encoding"] = ACCEPT_ENCODING  # только то, что умеем распаковать с пределом
    extensions = {"timeout": dict.fromkeys(("connect", "read", "write", "pool"), timeout)}
    async with pool.stream(
        method, target, headers=list(sent.items()), content=content, extensions=extensions
    ) as response:
        got = _headers(response.headers)
        if not wants_body(response.status, got):
            return Reply(response.status, got, b"", False)
        body, cut = await read_body(response.aiter_stream(), got.get("content-encoding", ""), limit)
    return Reply(response.status, got, body, cut)
