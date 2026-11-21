"""Мягкое прерывание ответа ради результата отложенной задачи и продолжение по «да».

Звучащий ответ хода (SpokenReply) отдаёт колонке предложения по одному. Пришёл
результат (очередь объявлений зовёт Pauses.interrupt) — ответ перестаёт брать новые
предложения: уже отправленный звук колонка договаривает (слово не обрывается), хаб
шлёт reply_end, колонка присылает playback_done — и объявление звучит сразу.
Отправить колонке можно только целые предложения и не больше LOOKAHEAD_S секунд
звука впереди услышанного (по событиям played или оценке темпа) — поэтому после
просьбы уступить колонка договаривает текущее предложение и не больше нескольких
секунд следующего. Непроизнесённый остаток ответа (предложения, которые не
отправлены, и то, что модель ещё допишет) хранится для колонки KEEP_S секунд;
следующий ход колонки забирает его: «да» — продолжение, иначе остаток забыт.
"""

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from smartesp.contracts import SAMPLE_RATE, DevicePort, Interruption

from .handoffs import Sentence
from .sentences import DEFAULT_STYLE, strip_style_tag
from .turn import Turn

_log = logging.getLogger(__name__)

LOOKAHEAD_S = 3.0  # следующее предложение — когда впереди услышанного осталось не больше стольких секунд
GATE_POLL_S = 0.05  # как часто проверять ход звука и просьбу уступить
INTERRUPT_WAIT_S = 30.0  # дольше конца прерванного ответа на колонке не ждём
KEEP_S = 300.0  # остаток ждёт «да» столько секунд
RESUME_WAIT_S = 30.0  # модель ещё дописывает остаток — ждём не дольше
BYTES_PER_S = SAMPLE_RATE * 2  # s16le, моно
NOTHING_LEFT = "Это всё, продолжать нечего."  # «да», а остатка нет

_YES = frozenset(
    "да давай давайте ага угу конечно продолжай продолжи продолжим продолжайте вернёмся вернемся "
    "можно хорошо ок окей".split()
)
# связки и вежливость: не меняют смысл согласия («ну давай», «да, вернёмся к тому, о чём говорили»)
_FILLER = frozenset("ну и так же уж пожалуйста к тому этому о чём чем говорили разговору".split())
_WORDS = re.compile(r"[а-яёa-z]+")
_MAX_WORDS = 8  # длиннее — это уже новая просьба, а не согласие


def _agreeing(word: str) -> bool:
    """Слово согласия: «да», «давай», формы «продолжай», «вернёмся»."""
    return word in _YES or word.startswith(("продолж", "вернём", "вернем"))


def agrees(text: str) -> bool:
    """True, если реплика — только согласие продолжить («да», «давай», «продолжай»).

    Каждое слово — согласие или связка; есть хоть одно слово сверх них («да, а сколько
    времени?», «давай лучше про погоду», «вернёмся к погоде») — это новая просьба.
    """
    words = _WORDS.findall(text.lower())
    if not words or len(words) > _MAX_WORDS:
        return False
    return any(_agreeing(w) for w in words) and all(_agreeing(w) or w in _FILLER for w in words)


@dataclass
class Remainder:
    """Непроизнесённый остаток прерванного ответа: предложения, стиль, собран ли целиком."""

    sentences: list[Sentence]
    style: str
    since: float  # time.monotonic() прерывания
    done: asyncio.Event = field(default_factory=asyncio.Event)

    async def wait(self, limit_s: float) -> None:
        """Ждёт, пока модель допишет остаток, но не дольше limit_s."""
        try:
            await asyncio.wait_for(self.done.wait(), limit_s)
        except TimeoutError:
            _log.warning("Остаток прерванного ответа не дописан за %.0f с", limit_s)


class SpokenReply:
    """Ответ хода, звучащий на колонке: сколько звука отдано, просьба уступить, остаток."""

    def __init__(self, turn: Turn, position: Callable[[], int | None], started_at: float) -> None:
        """position() — сколько байт ответа уже прозвучало (None — неизвестно); started_at — monotonic."""
        self.turn = turn
        self.started_at = started_at
        self.sent = 0  # байт звука, отданных хабу
        self.ends: list[int] = []  # где кончается каждое отданное предложение (байт от начала ответа)
        self.requested = False  # просили уступить
        self.paused = False  # уступили: остаток — в remainder
        self.remainder = Remainder([], turn.style, started_at)
        self._position = position

    def request(self) -> None:
        """Просьба уступить: следующее предложение колонке уже не уйдёт."""
        self.requested = True

    def withdraw(self) -> None:
        """Отзывает просьбу, если ответ ещё не уступил."""
        if not self.paused:
            self.requested = False

    async def admit(self, index: int, sentence: Sentence, is_live: Callable[[], bool]) -> bool:
        """Можно ли озвучить предложение index; False — уступили, оно и дальнейшие — остаток.

        Первое предложение звучит всегда. Следующее ждёт, пока впереди услышанного останется
        не больше LOOKAHEAD_S секунд звука (или ход станет неактуальным, или попросят уступить).
        """
        if index > 0:
            while not self.requested and is_live() and self._ahead_s() > LOOKAHEAD_S:
                await asyncio.sleep(GATE_POLL_S)
        if index == 0 or not self.requested:
            return True
        self.paused = True
        self.remainder.style = self.turn.style
        self.remainder.sentences.append(sentence)
        self._log_pause()
        return False

    def add_audio(self, size: int) -> None:
        """Учитывает отданный хабу звук текущего предложения."""
        self.sent += size

    def end_sentence(self) -> None:
        """Предложение отдано целиком: запоминает его границу."""
        self.ends.append(self.sent)

    async def collect(self, sentences: AsyncIterator[Sentence]) -> None:
        """Дочитывает остаток ответа (модель ещё пишет) после того, как колонка уступила."""
        try:
            async for sentence in sentences:
                self.remainder.sentences.append(sentence)
        except Exception:
            _log.warning("Колонка %s: остаток ответа дочитан не весь", self.turn.device_name, exc_info=True)
        finally:
            self.remainder.done.set()

    def _ahead_s(self) -> float:
        """Сколько секунд отправленного звука колонке ещё играть (неизвестно — 0)."""
        played = self._position()
        return 0.0 if played is None else (self.sent - played) / BYTES_PER_S

    def _log_pause(self) -> None:
        """В журнал: какое предложение звучит и сколько отправленных ещё впереди."""
        played = self._position() or 0
        playing = next((i for i, end in enumerate(self.ends) if end > played), len(self.ends))
        _log.info(
            "Колонка %s: ответ уступает результату — звучит предложение %d из %d отправленных, "
            "впереди %.1f с звука",
            self.turn.device_name,
            min(playing + 1, len(self.ends)),
            len(self.ends),
            max(self.sent - played, 0) / BYTES_PER_S,
        )


class Pauses:
    """Звучащие ответы по колонкам, мягкое прерывание и остатки для продолжения."""

    def __init__(
        self,
        devices: DevicePort,
        *,
        wait_s: float = INTERRUPT_WAIT_S,
        keep_s: float = KEEP_S,
        poll_s: float = GATE_POLL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """devices — колонки; wait_s — сколько ждать конца ответа; keep_s — срок остатка (секунды)."""
        self._devices = devices
        self._wait_s = wait_s
        self._keep_s = keep_s
        self._poll_s = poll_s
        self._clock = clock
        self._speaking: dict[str, SpokenReply] = {}
        self._remainders: dict[str, Remainder] = {}

    def start(self, turn: Turn) -> SpokenReply:
        """Ответ хода начинает звучать на колонке."""
        device_id, number = turn.utterance.device_id, turn.utterance.turn
        reply = SpokenReply(turn, lambda: self._devices.played_bytes(device_id, number), self._clock())
        self._speaking[device_id] = reply
        return reply

    def stop(self, reply: SpokenReply) -> None:
        """Звук ответа отдан (или оборван); уступивший оставляет колонке остаток."""
        device_id = reply.turn.utterance.device_id
        if self._speaking.get(device_id) is reply:
            del self._speaking[device_id]
        if reply.paused:
            reply.remainder.since = self._clock()
            self._remainders[device_id] = reply.remainder

    def claim(self, device_id: str) -> Remainder | None:
        """Забирает остаток колонки (следующий ход); просроченный — None."""
        remainder = self._remainders.pop(device_id, None)
        if remainder is None or self._clock() - remainder.since > self._keep_s:
            return None
        return remainder

    async def interrupt(self, device_id: str, since: float) -> Interruption:
        """Мягкое прерывание ответа, звучащего на колонке с момента раньше since (monotonic).

        Ждёт, пока колонка доиграет отправленное (не дольше wait_s). "paused" — ответ уступил,
        остаток можно продолжить; "finished" — договорён сам; "none" — прерывать нечего.
        """
        reply = self._speaking.get(device_id)
        if reply is None or reply.started_at >= since or reply.requested:
            return "none"
        reply.request()
        number = reply.turn.utterance.turn
        deadline = self._clock() + self._wait_s
        while self._devices.is_active(device_id, number) and self._clock() < deadline:
            await asyncio.sleep(self._poll_s)
        if reply.paused:
            return "paused"
        if self._devices.is_active(device_id, number):
            reply.withdraw()
            return "none"
        return "finished"


async def remainder_sentences(turn: Turn, remainder: Remainder) -> AsyncIterator[Sentence]:
    """Предложения остатка для хода-продолжения; их текст копится в ответе хода."""
    sentences = remainder.sentences or [Sentence(NOTHING_LEFT, False)]
    for sentence in sentences:
        turn.answer.append(strip_style_tag(sentence.text)[1].strip() + " ")
        yield sentence


def resume_style(remainder: Remainder) -> str:
    """Стиль продолжения — как у прерванного ответа."""
    return remainder.style or DEFAULT_STYLE
