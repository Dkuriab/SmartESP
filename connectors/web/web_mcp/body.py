"""Тело ответа с пределом: не больше limit байт по проводу и не больше limit после распаковки.

Распаковка своя и пошаговая (zlib с max_length): «бомба» из сотен КБ, которая
разворачивается в гигабайты, обрывается на пределе и не занимает память сверх него.
Принимается не больше одного сжатия: gzip или deflate (запрашиваем только их).
"""

import zlib
from collections.abc import AsyncIterable

_GZIP = ("gzip", "x-gzip")


class UnsupportedEncoding(Exception):
    """Сжатие не gzip/deflate или их несколько подряд."""


class BadBody(Exception):
    """Сжатые данные испорчены."""


def _coding(content_encoding: str) -> str:
    """Единственное сжатие из заголовка Content-Encoding ("" — без сжатия)."""
    codings = [part.strip().lower() for part in content_encoding.split(",")]
    codings = [part for part in codings if part and part != "identity"]
    if len(codings) > 1:
        raise UnsupportedEncoding(content_encoding)
    coding = codings[0] if codings else ""
    if coding not in ("", "deflate", *_GZIP):
        raise UnsupportedEncoding(content_encoding)
    return coding


def _is_zlib_header(head: bytes) -> bool:
    """deflate бывает с обёрткой zlib (по стандарту) и без неё (так шлют многие серверы)."""
    return len(head) >= 2 and head[0] & 0x0F == 8 and ((head[0] << 8) | head[1]) % 31 == 0


class _Inflater:
    """Пошаговая распаковка; вид deflate определяется по первым двум байтам."""

    def __init__(self, coding: str) -> None:
        self._coding = coding
        self._pending = b""
        self._zlib: zlib._Decompress | None = None  # pyright: ignore[reportPrivateUsage]
        if coding in _GZIP:
            self._zlib = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def feed(self, chunk: bytes, room: int) -> bytes:
        """Распаковывает кусок, отдавая не больше room байт (room > 0)."""
        if self._zlib is None:
            self._pending += chunk
            if len(self._pending) < 2:
                return b""
            wbits = zlib.MAX_WBITS if _is_zlib_header(self._pending) else -zlib.MAX_WBITS
            self._zlib = zlib.decompressobj(wbits)
            chunk, self._pending = self._pending, b""
        try:
            return self._zlib.decompress(chunk, room)
        except zlib.error as error:
            raise BadBody(str(error)) from error


async def read_body(chunks: AsyncIterable[bytes], content_encoding: str, limit: int) -> tuple[bytes, bool]:
    """Тело (не длиннее limit) и признак «дальше не читали». Плохое сжатие — исключение."""
    coding = _coding(content_encoding)
    inflater = _Inflater(coding) if coding else None
    out = bytearray()
    wire = 0
    async for chunk in chunks:
        wire += len(chunk)
        if inflater is not None:
            chunk = inflater.feed(chunk, limit - len(out))
        out += chunk
        if len(out) >= limit or wire >= limit:
            return bytes(out[:limit]), True
    return bytes(out), False
