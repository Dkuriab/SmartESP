"""Признаки для модели отпечатков: Kaldi fbank (80 мел-фильтров, 25/10 мс) на numpy.

Повторяет torchaudio.compliance.kaldi.fbank / kaldi-native-fbank с настройками, на которых
учились модели 3D-Speaker: без дизеринга, окно Пови, снятие постоянной составляющей,
предыскажение 0,97, БПФ 512, фильтры 20 Гц … 8 кГц, кадры только целиком (snip_edges).
Сверено с kaldi-native-fbank: расхождение логарифмов < 2·10⁻⁴.
"""

import functools

import numpy as np

RATE = 16000
FRAME = 400  # 25 мс
SHIFT = 160  # 10 мс
FFT = 512
BINS = 80
LOW_HZ = 20.0
PREEMPH = 0.97
POVEY = 0.85  # окно Пови: окно Ханна в степени 0,85
EPS = float(np.finfo(np.float32).eps)


def _mel(freq: np.ndarray | float) -> np.ndarray:
    return np.asarray(1127.0 * np.log(1.0 + np.asarray(freq) / 700.0))


@functools.cache
def _banks() -> np.ndarray:
    """Треугольные мел-фильтры BINS × (FFT/2 + 1); бин Найквиста без веса, как в Kaldi."""
    half = FFT // 2
    mel_low, mel_high = float(_mel(LOW_HZ)), float(_mel(RATE / 2))
    delta = (mel_high - mel_low) / (BINS + 1)
    mels = _mel(np.arange(half) * RATE / FFT)[None, :]
    left = mel_low + np.arange(BINS)[:, None] * delta
    center, right = left + delta, left + 2 * delta
    rising = (mels - left) / (center - left)
    falling = (right - mels) / (right - center)
    inside = (mels > left) & (mels < right)
    weights = np.where(inside, np.where(mels <= center, rising, falling), 0.0)
    return np.concatenate([weights, np.zeros((BINS, 1))], axis=1)


@functools.cache
def _window() -> np.ndarray:
    n = np.arange(FRAME)
    return (0.5 - 0.5 * np.cos(2 * np.pi * n / (FRAME - 1))) ** POVEY


def frame_count(samples: int) -> int:
    """Сколько целых кадров в samples отсчётах (0, если меньше одного кадра)."""
    return 0 if samples < FRAME else 1 + (samples - FRAME) // SHIFT


def fbank(samples: np.ndarray) -> np.ndarray:
    """Логарифмы энергий мел-фильтров по кадрам: (кадров, BINS), float32.

    samples — отсчёты float (масштаб — как ждёт модель); меньше одного кадра — пустой массив.
    """
    count = frame_count(len(samples))
    if count == 0:
        return np.zeros((0, BINS), dtype=np.float32)
    index = np.arange(FRAME)[None, :] + SHIFT * np.arange(count)[:, None]
    frames = samples[index].astype(np.float64)
    frames = frames - frames.mean(axis=1, keepdims=True)
    first = frames[:, :1] * (1 - PREEMPH)
    frames = np.concatenate([first, frames[:, 1:] - PREEMPH * frames[:, :-1]], axis=1)
    power = np.abs(np.fft.rfft(frames * _window(), FFT)) ** 2
    return np.log(np.maximum(power @ _banks().T, EPS)).astype(np.float32)


def normalized_fbank(pcm: bytes) -> np.ndarray:
    """PCM s16le → fbank с вычтенным средним по времени (вход модели 3D-Speaker)."""
    samples = np.frombuffer(pcm[: len(pcm) & ~1], dtype="<i2").astype(np.float64) / 32768.0
    feats = fbank(samples)
    return feats - feats.mean(axis=0, keepdims=True) if len(feats) else feats
