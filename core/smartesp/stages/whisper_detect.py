"""Обработчик «шёпот»: у шёпота почти нет голосового тона (колебаний связок)."""

import asyncio
import logging

import numpy as np

from smartesp.contracts import Annotation, Utterance

RATE = 16000
FRAME = 512  # 32 мс
ACTIVE_BELOW_PEAK_DB = 25.0  # звучащий кадр — не тише самого громкого на столько дБ
MIN_LEVEL_DB = -60.0  # тише этого — тишина, даже если громче нет ничего
MIN_LAG = RATE // 400  # тон 400 Гц
MAX_LAG = RATE // 70  # тон 70 Гц
VOICED_CORRELATION = 0.5  # кадр с тоном — автокорреляция выше этого
MIN_ACTIVE_FRAMES = 5  # меньше 160 мс звука — не судим
WHISPER_VOICED_RATIO = 0.15  # шёпот — кадров с тоном меньше этой доли
NOTE = "Человек говорит шёпотом — отвечай тихо и коротко"
PROMPT_HINT = (
    "Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]. "
    "Во всех остальных случаях никаких меток не пиши."
)

_log = logging.getLogger(__name__)


def _frames(pcm: bytes) -> np.ndarray:
    """PCM s16le → кадры по FRAME отсчётов (float, без постоянной составляющей)."""
    samples = np.frombuffer(pcm[: len(pcm) & ~1], dtype="<i2").astype(np.float64) / 32768.0
    count = len(samples) // FRAME
    frames = samples[: count * FRAME].reshape(count, FRAME)
    return frames - frames.mean(axis=1, keepdims=True)


def _level_db(frames: np.ndarray) -> np.ndarray:
    """Громкость каждого кадра в дБ относительно полной шкалы."""
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def _has_pitch(frame: np.ndarray) -> bool:
    """Есть ли в кадре голосовой тон 70–400 Гц (пик нормированной автокорреляции).

    Автокорреляция несмещённая (делим на длину перекрытия), иначе низкие голоса
    (большая задержка — мало перекрытия) недооцениваются и похожи на шёпот.
    """
    spectrum = np.fft.rfft(frame, 2 * FRAME)
    correlation = np.fft.irfft(spectrum * np.conj(spectrum))[: MAX_LAG + 1]
    if correlation[0] <= 0:
        return False
    lags = np.arange(MIN_LAG, MAX_LAG + 1)
    unbiased = correlation[MIN_LAG:] * FRAME / (FRAME - lags)
    return float(np.max(unbiased) / correlation[0]) > VOICED_CORRELATION


def measure(pcm: bytes) -> tuple[int, float]:
    """Число звучащих кадров и доля кадров с голосовым тоном среди них."""
    frames = _frames(pcm)
    if len(frames) == 0:
        return 0, 0.0
    levels = _level_db(frames)
    floor = max(float(levels.max()) - ACTIVE_BELOW_PEAK_DB, MIN_LEVEL_DB)
    active = frames[levels > floor]
    if len(active) == 0:
        return 0, 0.0
    voiced = sum(_has_pitch(frame) for frame in active)
    return len(active), voiced / len(active)


class WhisperDetect:
    """Добавляет пометку, если фраза сказана шёпотом."""

    name = "whisper_detect"
    prompt_hint = PROMPT_HINT

    async def analyze(self, utterance: Utterance) -> list[Annotation]:
        """Пометка «шёпот» или пустой список; доля тона пишется в журнал для настройки порогов."""
        active, ratio = await asyncio.to_thread(measure, utterance.pcm)
        whisper = active >= MIN_ACTIVE_FRAMES and ratio < WHISPER_VOICED_RATIO
        verdict = "да" if whisper else "нет"
        _log.info("шёпот: %s (кадров со звуком %d, доля тона %.2f)", verdict, active, ratio)
        if not whisper:
            return []
        data: dict[str, object] = {"voiced_ratio": ratio, "active_frames": active}
        return [Annotation(text=NOTE, source=self.name, data=data)]
