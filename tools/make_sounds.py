"""Синтезирует мягкие звуки колонки и пишет SoundData.cpp для прошивки.

Каждый звук — «колокольчик»: сумма гармоник с быстрой атакой и
экспоненциальным затуханием, в конце — косинусный спад (без щелчков).
Образцы 16 кГц, 16 бит, моно; громкость (уровень) уже внутри образца.

Запуск из корня репозитория:
    uv run --project core python tools/make_sounds.py
    uv run --project core python tools/make_sounds.py --wav-dir <папка>   # ещё и WAV для прослушивания
"""

from __future__ import annotations

import argparse
import wave
from pathlib import Path

import numpy as np

RATE = 16000
ATTACK_S = 0.008  # атака ноты (не короче 5 мс, иначе щелчок)
FADE_S = 0.04  # косинусный спад в конце звука
PARTIALS = ((1.0, 1.0), (2.0, 0.30), (3.0, 0.10))  # (кратность частоты, амплитуда)
OUT_CPP = Path(__file__).resolve().parent.parent / "firmware" / "SmartEsp" / "src" / "audio_out" / "SoundData.cpp"

# Ноты: (старт с, частота Гц, постоянная затухания с, относительная громкость).
# Затем — длина звука в секундах и пиковый уровень (доля полной шкалы, ≤ 0,5).
_SOUNDS: dict[str, tuple[list[tuple[float, float, float, float]], float, float]] = {
    # Восходящий двухнотный звон: ми5 → ля5.
    "wake": ([(0.00, 659.3, 0.07, 0.8), (0.11, 880.0, 0.10, 1.0)], 0.42, 0.40),
    # Нисходящий мягкий звон: ля4 → ми4, ниже и теплее.
    "error": ([(0.00, 440.0, 0.09, 1.0), (0.16, 329.6, 0.13, 1.0)], 0.55, 0.38),
    # Короткая тихая капля: одна нота с лёгким «падением» высоты.
    "thinking": ([(0.00, 740.0, 0.05, 1.0)], 0.28, 0.22),
    # «Динь-динь-дон» перед речью: соль5, соль5, до5.
    "attention": ([(0.00, 784.0, 0.06, 0.8), (0.15, 784.0, 0.06, 0.8), (0.30, 523.3, 0.11, 1.0)], 0.58, 0.40),
}
_ALIASES = {"listen": "wake"}  # «слушаю» звучит как слово услышано (дизайн 5.3)
NAMES = ["wake", "listen", "thinking", "error", "attention"]


def _note(t: np.ndarray, hz: float, tau: float, gain: float, glide: float) -> np.ndarray:
    """Одна нота: гармоники × (атака · затухание). glide — доля падения частоты."""
    freq = hz * (1.0 - glide * (1.0 - np.exp(-t / 0.05)))
    phase = 2 * np.pi * np.cumsum(freq) / RATE
    tone = sum(amp * np.sin(mult * phase) for mult, amp in PARTIALS)
    attack = np.minimum(1.0, t / ATTACK_S)
    attack = (0.5 - 0.5 * np.cos(np.pi * attack)) ** 2  # плавный старт: первые отсчёты почти нули
    return gain * tone * attack * np.exp(-t / tau)


def render(name: str) -> np.ndarray:
    """Звук по имени (wake, listen, thinking, error, attention) → int16, 16 кГц, моно."""
    notes, length, peak = _SOUNDS[_ALIASES.get(name, name)]
    total = int(length * RATE)
    out = np.zeros(total)
    glide = 0.12 if name == "thinking" else 0.0
    for start, hz, tau, gain in notes:
        first = int(start * RATE)
        t = np.arange(total - first) / RATE
        out[first:] += _note(t, hz, tau, gain, glide)
    fade = int(FADE_S * RATE)
    out[-fade:] *= 0.5 + 0.5 * np.cos(np.pi * np.arange(fade) / fade)
    out *= peak * 32767 / np.abs(out).max()
    return np.round(out).astype(np.int16)


def write_cpp(path: Path) -> None:
    """Пишет SoundData.cpp: массив SOUND_<ИМЯ> и длину SOUND_<ИМЯ>_LEN для каждого звука."""
    parts = [
        "// Создано tools/make_sounds.py — не править руками.\n"
        "// Звуки колонки: PCM 16 кГц, 16 бит, моно, уровень уже внутри образца.\n\n"
        "// Внешнее связывание констант дают объявления extern в SoundData.h.\n"
        '#include "SoundData.h"\n'
    ]
    for name in NAMES:
        pcm = render(name)
        lines = [", ".join(str(int(v)) for v in pcm[i : i + 16]) for i in range(0, len(pcm), 16)]
        body = ",\n".join(f"    {line}" for line in lines)
        up = name.upper()
        parts.append(
            f"\nconst int16_t SOUND_{up}[] = {{\n{body}\n}};\n"
            f"const size_t SOUND_{up}_LEN = {len(pcm)};\n"
        )
    path.write_text("".join(parts), encoding="utf-8")


def write_wav(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=OUT_CPP, help="куда записать SoundData.cpp")
    parser.add_argument("--wav-dir", type=Path, help="сохранить ещё и WAV для прослушивания")
    args = parser.parse_args()
    write_cpp(args.out)
    print(f"{args.out}: {len(NAMES)} звуков")
    if args.wav_dir:
        args.wav_dir.mkdir(parents=True, exist_ok=True)
        for name in NAMES:
            write_wav(args.wav_dir / f"{name}.wav", render(name))


if __name__ == "__main__":
    main()
