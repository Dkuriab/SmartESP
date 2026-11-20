"""Сменные части оркестратора: подмена на лету, снимок на начало хода."""

from smartesp.contracts import Analyzer, Executor, SpeechToText, TextToSpeech

from .asking import AskParts
from .turn import Parts


class PartSlots:
    """Распознавание, обработчики, исполнитель и синтез; любую часть можно не задать (None)."""

    def __init__(
        self,
        stt: SpeechToText | None,
        analyze: Analyzer | None,
        executor: Executor | None,
        tts: TextToSpeech | None,
    ) -> None:
        self._stt = stt
        self._analyze = analyze
        self._executor = executor
        self._tts = tts

    def use_stt(self, stt: SpeechToText) -> None:
        """Подменяет распознавание; идущие ходы доделываются прежним."""
        self._stt = stt

    def use_analyzer(self, analyze: Analyzer) -> None:
        """Подменяет обработчики; идущие ходы доделываются прежними."""
        self._analyze = analyze

    def use_executor(self, executor: Executor) -> None:
        """Подменяет исполнителя; идущие ходы доделываются прежним."""
        self._executor = executor

    def use_tts(self, tts: TextToSpeech) -> None:
        """Подменяет синтез речи; идущие ходы доделываются прежним."""
        self._tts = tts

    @property
    def ready(self) -> bool:
        """True, если заданы все четыре части: распознавание, обработчики, исполнитель и синтез."""
        return self._snapshot() is not None

    def _snapshot(self) -> Parts | None:
        """Текущие части одним снимком или None, если какой-то части нет."""
        stt, analyze, executor, tts = self._stt, self._analyze, self._executor, self._tts
        if stt is None or analyze is None or executor is None or tts is None:
            return None
        return Parts(stt, analyze, executor, tts)

    def _ask_parts(self) -> AskParts | None:
        """Части для хода через API (синтез не нужен) или None, если обработчиков или исполнителя нет."""
        analyze, executor = self._analyze, self._executor
        return None if analyze is None or executor is None else AskParts(self._stt, analyze, executor)
