"""Потоковый фильтр: вырезает рассуждение <think>…</think> из текста ответа модели.

LM Studio кладёт рассуждение в content тегами, если в нём выключено отделение рассуждения
(reasoning_content). Теги могут прийти разрезанными между кусками потока.
"""

OPEN = "<think>"
CLOSE = "</think>"


def _partial_tail(text: str, tag: str) -> int:
    """Длина конца text, который может оказаться началом tag (ждём следующий кусок)."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


class ThinkFilter:
    """Отдаёт текст без блоков <think>…</think>; незакрытый в конце блок отбрасывается."""

    def __init__(self) -> None:
        self._buffer = ""
        self._inside = False
        self._trim = False  # после </think> модели ставят пустые строки — их не отдаём

    def feed(self, text: str) -> str:
        """Часть текста, которую уже можно отдать (хвост, похожий на начало тега, ждёт)."""
        self._buffer += text
        shown: list[str] = []
        while (index := self._buffer.find(CLOSE if self._inside else OPEN)) >= 0:
            tag = CLOSE if self._inside else OPEN
            if not self._inside:
                shown.append(self._trimmed(self._buffer[:index]))
            self._buffer = self._buffer[index + len(tag) :]
            self._trim = self._inside
            self._inside = not self._inside
        keep = _partial_tail(self._buffer, CLOSE if self._inside else OPEN)
        cut = len(self._buffer) - keep
        if not self._inside:
            shown.append(self._trimmed(self._buffer[:cut]))
        self._buffer = self._buffer[cut:]
        return "".join(shown)

    def end(self) -> str:
        """Остаток в конце потока: недописанный тег — обычный текст, незакрытое рассуждение — нет."""
        rest = "" if self._inside else self._trimmed(self._buffer)
        self._buffer = ""
        return rest

    def _trimmed(self, text: str) -> str:
        """Текст без пустых строк в начале, если он сразу после </think>."""
        if self._trim:
            text = text.lstrip()
            self._trim = not text
        return text
