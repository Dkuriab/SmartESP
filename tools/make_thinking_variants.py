"""Варианты мелодии «думаю» для колонки: WAV 16 кГц, 16 бит, моно в tools/sounds/thinking/.

Владелец слушает их и выбранный загружает на колонку в приложении (свой звук сигнала
«thinking», по воздуху). Звучит сразу при передаче вопроса и потом каждые 8 с, пока ждём
ответ, поэтому варианты короткие (до 1,5 с), тихие и без резкой атаки.

Запуск из корня репозитория:
    uv run --project core python tools/make_thinking_variants.py
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

RATE = 16000
OUT = Path(__file__).resolve().parent / "sounds" / "thinking"
FADE_S = 0.06  # косинусный спад в конце
# тембры: (кратность частоты, амплитуда, во сколько раз быстрее затухает)
KALIMBA = ((1.0, 1.0, 1.0), (5.4, 0.12, 4.0), (2.0, 0.05, 2.0))
BOX = ((1.0, 1.0, 1.0), (2.0, 0.25, 1.6), (3.0, 0.08, 2.5), (4.2, 0.04, 3.0))
SOFT = ((1.0, 1.0, 1.0), (2.0, 0.18, 1.5))
MARIMBA = ((1.0, 1.0, 1.0), (4.0, 0.22, 5.0), (10.0, 0.03, 9.0))

Note = tuple[float, float, float, float]  # старт с, частота Гц, затухание с, громкость


def _hz(name: str) -> float:
    """Частота ноты по имени: «A4» = 440 Гц, «C#5» и т. п."""
    steps = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}
    base, octave = name[:-1], int(name[-1])
    semitone = steps[base[0]] + (1 if base.endswith("#") else 0) + 12 * (octave - 4)
    return 440.0 * 2 ** (semitone / 12)


def _tone(
    t: np.ndarray,
    hz: float,
    tau: float,
    timbre: tuple[tuple[float, float, float], ...],
    attack_s: float,
    vibrato: float,
    glide: float,
) -> np.ndarray:
    """Одна нота: гармоники с собственным затуханием, плавная атака, лёгкое вибрато и подъём высоты."""
    freq = (
        hz
        * (1.0 + glide * (1.0 - np.exp(-t / 0.08)))
        * (1.0 + vibrato * np.sin(2 * np.pi * 5.0 * t))
    )
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    out = np.zeros_like(t)
    for mult, amp, speed in timbre:
        if hz * mult < RATE * 0.45:  # выше половины частоты дискретизации не пишем
            out += amp * np.sin(mult * phase) * np.exp(-t * speed / tau)
    rise = np.minimum(1.0, t / attack_s)
    return out * (0.5 - 0.5 * np.cos(np.pi * rise))


def _reverb(x: np.ndarray, mix: float) -> np.ndarray:
    """Мягкий «зал»: свёртка с затухающим шумом 0,35 с (зерно фиксировано — звук одинаков при каждом запуске)."""
    n = int(0.35 * RATE)
    rng = np.random.default_rng(7)
    tail = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.09 * RATE))
    tail = np.convolve(
        tail, np.ones(6) / 6, mode="same"
    )  # без высоких «шипящих» призвуков
    wet = np.convolve(x, tail)[: x.size]
    wet *= np.max(np.abs(x)) / (np.max(np.abs(wet)) + 1e-9)
    return (1 - mix) * x + mix * wet


def render(
    notes: list[Note],
    length: float,
    peak: float,
    timbre: tuple[tuple[float, float, float], ...],
    attack_s: float = 0.006,
    vibrato: float = 0.0,
    glide: float = 0.0,
    reverb: float = 0.25,
) -> np.ndarray:
    """Мелодия из нот → int16; peak — пиковый уровень (доля полной шкалы)."""
    total = int(length * RATE)
    out = np.zeros(total)
    for start, hz, tau, gain in notes:
        begin = int(start * RATE)
        t = np.arange(total - begin) / RATE
        out[begin:] += gain * _tone(t, hz, tau, timbre, attack_s, vibrato, glide)
    out = _reverb(out, reverb)
    fade = int(FADE_S * RATE)
    out[-fade:] *= 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, fade))
    out *= peak / np.max(np.abs(out))
    return (out * 32767).astype(np.int16)


VARIANTS: dict[str, np.ndarray] = {
    # 1. Калимба: три ноты вверх по пентатонике — «тин-тин-тин», лёгкий вопрос
    "1-kalimba": render(
        [
            (0.00, _hz("E5"), 0.30, 0.9),
            (0.15, _hz("G5"), 0.30, 0.9),
            (0.30, _hz("B5"), 0.45, 1.0),
        ],
        1.1,
        0.30,
        KALIMBA,
    ),
    # 2. Музыкальная шкатулка: четыре высокие нотки «до-ми-соль-ми»
    "2-music-box": render(
        [
            (0.00, _hz("C6"), 0.35, 0.8),
            (0.16, _hz("E6"), 0.35, 0.8),
            (0.32, _hz("G6"), 0.35, 0.85),
            (0.48, _hz("E6"), 0.55, 0.9),
        ],
        1.3,
        0.24,
        BOX,
    ),
    # 3. Тёплый аккорд: медленное арпеджио до-мажор-нона, мягкая атака — «задумчиво»
    "3-warm-chord": render(
        [
            (0.00, _hz("C4"), 0.70, 0.7),
            (0.09, _hz("E4"), 0.70, 0.6),
            (0.18, _hz("G4"), 0.70, 0.6),
            (0.27, _hz("B4"), 0.70, 0.5),
            (0.36, _hz("D5"), 0.80, 0.55),
        ],
        1.5,
        0.30,
        SOFT,
        attack_s=0.03,
        reverb=0.35,
    ),
    # 4. «Хм?»: две плавные ноты ля → ре с подъёмом в конце, как вопросительная интонация
    "4-hmm": render(
        [(0.00, _hz("A4"), 0.25, 0.9), (0.20, _hz("D5"), 0.35, 1.0)],
        0.9,
        0.30,
        SOFT,
        attack_s=0.04,
        vibrato=0.006,
        glide=0.02,
    ),
    # 5. Капли: три капли вниз «соль-ми-до», каждая с маленьким подскоком высоты
    "5-drops": render(
        [
            (0.00, _hz("G6"), 0.10, 0.8),
            (0.18, _hz("E6"), 0.10, 0.8),
            (0.36, _hz("C6"), 0.16, 1.0),
        ],
        0.9,
        0.24,
        SOFT,
        glide=0.04,
        reverb=0.3,
    ),
    # 6. Маримба: «ту-ду» — две тёплые низкие ноты, коротко и спокойно
    "6-marimba": render(
        [(0.00, _hz("D5"), 0.22, 1.0), (0.17, _hz("A4"), 0.30, 0.9)], 0.8, 0.32, MARIMBA
    ),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, samples in VARIANTS.items():
        with wave.open(str(OUT / f"thinking-{name}.wav"), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(samples.tobytes())
        print(f"thinking-{name}.wav: {samples.size / RATE:.2f} с")


if __name__ == "__main__":
    main()
