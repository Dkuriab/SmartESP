"""Подделка синтеза речи: тишина длиной пропорциональной тексту, по предложению."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator


class FakeTTS:
    def __init__(self, bytes_per_char: int = 320) -> None:
        # Чётное число байт на символ, чтобы кусок был целым числом s16-отсчётов.
        self._bytes_per_char = bytes_per_char - bytes_per_char % 2

    def styles(self) -> list[str]:
        return ["normal"]

    async def synthesize(self, text: str, style: str) -> AsyncIterator[bytes]:
        for sentence in re.findall(r"[^.!?]+[.!?]*", text):
            if sentence.strip():
                yield bytes(len(sentence) * self._bytes_per_char)
