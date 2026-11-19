"""Озвучка: ответ хода по предложениям и готовый текст (для объявлений ядра)."""

import logging
from collections.abc import AsyncIterator, Callable

from smartesp.contracts import ExecutorError, ReplyPart, TextToSpeech

from .handoffs import Sentence, speech_text
from .sentences import DEFAULT_STYLE, clean_for_speech, split_sentences
from .streams import closing
from .turn import Turn

_log = logging.getLogger(__name__)


async def speak_answer(
    turn: Turn, tts: TextToSpeech, sentences: AsyncIterator[Sentence], is_live: Callable[[], bool]
) -> AsyncIterator[bytes]:
    """Озвучивает предложения по одному и отдаёт PCM; останавливается, как только ход неактуален.

    Ошибка исполнителя или TTS посреди ответа заканчивает поток штатно
    (колонка получит reply_end, а не застрянет в «говорю») и помечает ход
    как упавший; сигнал ошибки (если звука не было) шлёт оркестратор.
    Запоминает последнее озвученное предложение и время первого звука.
    """
    try:
        async for sentence in sentences:
            if not is_live():
                return
            text = speech_text(turn, sentence, tts.styles())
            if not text:
                continue
            turn.last_sentence = text
            async with closing(tts.synthesize(text, turn.style)) as audio:
                async for chunk in audio:
                    if not is_live():
                        return
                    if turn.first_audio_ms is None:
                        turn.first_audio_ms = turn.elapsed_ms()
                    yield chunk
    except ExecutorError as error:
        _log.warning("Колонка %s: исполнитель упал посреди ответа: %s", turn.device_name, error)
        turn.failed = True
        return
    except Exception:
        _log.error("Колонка %s: ошибка посреди ответа", turn.device_name, exc_info=True)
        turn.failed = True
        return
    turn.completed = is_live() and not turn.failed


async def speak_text(tts: TextToSpeech, text: str) -> AsyncIterator[bytes]:
    """Озвучивает готовый текст по предложениям стилем по умолчанию; отдаёт PCM."""
    async with closing(split_sentences(_single(text))) as sentences:
        async for sentence in sentences:
            clean = clean_for_speech(sentence)
            if not clean:
                continue
            async with closing(tts.synthesize(clean, DEFAULT_STYLE)) as audio:
                async for chunk in audio:
                    yield chunk


async def _single(text: str) -> AsyncIterator[ReplyPart]:
    """Текст одним куском ответа (для нарезки на предложения)."""
    yield ReplyPart(text)
