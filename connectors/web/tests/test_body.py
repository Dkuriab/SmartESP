"""Чтение тела ответа: предел на проводе и после распаковки, одно сжатие gzip/deflate."""

import gzip
import os
import tracemalloc
import zlib
from collections.abc import AsyncIterator, Iterable

import pytest

from web_mcp.body import BadBody, UnsupportedEncoding, read_body

LIMIT = 2 * 1024 * 1024


async def chunks(parts: Iterable[bytes], sent: list[int] | None = None) -> AsyncIterator[bytes]:
    for part in parts:
        if sent is not None:
            sent.append(len(part))
        yield part


def split(data: bytes, size: int = 65536) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def gzip_bomb(megabytes: int) -> bytes:
    """Сжатые нули: несколько сотен КБ на проводе, megabytes МБ после распаковки."""
    packer = zlib.compressobj(9, zlib.DEFLATED, 31)
    zeros = bytes(1024 * 1024)
    return b"".join(packer.compress(zeros) for _ in range(megabytes)) + packer.flush()


async def test_plain_body() -> None:
    assert await read_body(chunks([b"abc", b"def"]), "", LIMIT) == (b"abcdef", False)
    assert await read_body(chunks([b"abc"]), "identity", LIMIT) == (b"abc", False)


async def test_plain_body_stops_at_limit_on_the_wire() -> None:
    sent: list[int] = []
    body, cut = await read_body(chunks([b"x" * 65536] * 100, sent), "", LIMIT)
    assert cut
    assert len(body) == LIMIT
    assert sum(sent) <= LIMIT + 65536


@pytest.mark.parametrize("encoding", ["gzip", "x-gzip", "GZIP"])
async def test_gzip_body(encoding: str) -> None:
    data = "Привет, кот! ".encode() * 1000
    assert await read_body(chunks(split(gzip.compress(data), 100)), encoding, LIMIT) == (data, False)


@pytest.mark.parametrize("wbits", [15, -15])
async def test_deflate_body_zlib_or_raw(wbits: int) -> None:
    data = b"deflate " * 500
    packer = zlib.compressobj(6, zlib.DEFLATED, wbits)
    packed = packer.compress(data) + packer.flush()
    assert await read_body(chunks(split(packed, 7)), "deflate", LIMIT) == (data, False)


@pytest.mark.parametrize("encoding", ["gzip, gzip", "gzip,deflate", "br", "zstd", "compress"])
async def test_unsupported_or_stacked_encodings_are_refused(encoding: str) -> None:
    with pytest.raises(UnsupportedEncoding):
        await read_body(chunks([b"x"]), encoding, LIMIT)


async def test_gzip_bomb_is_cut_without_allocating_beyond_limit() -> None:
    bomb = gzip_bomb(200)
    assert len(bomb) < LIMIT
    tracemalloc.start()
    try:
        body, cut = await read_body(chunks(split(bomb)), "gzip", LIMIT)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert cut
    assert len(body) == LIMIT
    assert peak < 6 * LIMIT


async def test_incompressible_gzip_stops_at_limit_on_the_wire() -> None:
    sent: list[int] = []
    packed = gzip.compress(os.urandom(3 * LIMIT), compresslevel=1)
    body, cut = await read_body(chunks(split(packed), sent), "gzip", LIMIT)
    assert cut
    assert len(body) <= LIMIT
    assert sum(sent) <= LIMIT + 65536


async def test_broken_gzip_is_an_error() -> None:
    with pytest.raises(BadBody):
        await read_body(chunks([b"not gzip at all"]), "gzip", LIMIT)
