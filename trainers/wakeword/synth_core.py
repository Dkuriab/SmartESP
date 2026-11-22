"""Синтетика фраз голосами, скачанными ядром (Silero, Vosk, Piper из <данные>/voices).

Запускается окружением ядра (там torch, vosk-tts и piper): wakeword synth делает это сам —
`uv run --project core python trainers/wakeword/synth_core.py --voices … --out … --phrases '[…]'`.
Каждая фраза — с «!» и «?», разной скоростью, высотой и (у Vosk и Piper) случайностью голоса.
Пишет WAV 16 кГц моно без тишины по краям в <out>/<фраза>/<голос>-<вариант>.wav; готовые не пересчитывает.
Ход — строками JSON в stdout: {"stage", "done", "total"}.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import warnings
import wave
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

RATE = 16000
SPEEDS = (0.8, 0.9, 1.0, 1.1, 1.25)  # Vosk speech_rate и Piper 1/length_scale
SILERO_RATES = ("slow", "medium", "fast")
SILERO_PITCHES = ("low", "medium", "high")
DRAWS = 2  # Vosk и Piper звучат чуть иначе при каждом синтезе — два прогона на вариант

type Render = Callable[[str], np.ndarray]  # текст → int16 16 кГц


def folder_name(text: str) -> str:
    """Имя папки фразы — как у ядра (smartesp/training/recordings.py)."""
    name = re.sub(r"[^\w\- ,!?]+", "", text.strip()).strip().lstrip(".")
    return name[:60] or "_"


def to_16k(samples: np.ndarray, rate: int) -> np.ndarray:
    """Float или int16 звук частоты rate → int16 16 кГц (линейная интерполяция)."""
    data = samples.astype(np.float32)
    if samples.dtype == np.int16:
        data /= 32768.0
    if rate != RATE:
        positions = np.arange(int(len(data) * RATE / rate)) * rate / RATE
        data = np.interp(positions, np.arange(len(data)), data)
    return np.clip(data * 32768.0, -32768, 32767).astype(np.int16)


def trim(samples: np.ndarray, threshold_db: float = -40.0, margin: int = 800) -> np.ndarray:
    """Без тишины по краям (окна 10 мс тише порога от пика), с полями 50 мс."""
    frame = RATE // 100
    count = len(samples) // frame
    if count == 0:
        return samples
    energy = (
        np.sqrt((samples[: count * frame].astype(np.float32).reshape(count, frame) ** 2).mean(axis=1)) + 1e-9
    )
    loud = np.nonzero(20 * np.log10(energy / energy.max()) > threshold_db)[0]
    return samples[max(0, loud[0] * frame - margin) : min(len(samples), (loud[-1] + 1) * frame + margin)]


def silero_voices(voices: Path) -> Iterator[tuple[str, Render]]:
    """Голоса Silero v5: каждый говорящий × скорость × высота (SSML)."""
    model_path = voices / "silero" / "v5_ru.pt"
    if not model_path.exists():
        return
    import torch
    from torch.package.package_importer import PackageImporter

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = PackageImporter(str(model_path)).load_pickle("tts_models", "model")
    model.to(torch.device("cpu"))
    speakers = [
        s
        for s in getattr(model, "speakers", ["aidar", "baya", "kseniya", "xenia", "eugene"])
        if s != "random"
    ]
    for speaker in speakers:
        for rate in SILERO_RATES:
            for pitch in SILERO_PITCHES:

                def render(text: str, s: str = speaker, r: str = rate, p: str = pitch) -> np.ndarray:
                    ssml = f'<speak><prosody rate="{r}" pitch="{p}">{text}</prosody></speak>'
                    audio = model.apply_tts(ssml_text=ssml, speaker=s, sample_rate=48000)
                    return to_16k(audio.numpy(), 48000)

                yield f"silero_{speaker}_{rate}_{pitch}", render


def vosk_voices(voices: Path) -> Iterator[tuple[str, Render]]:
    """Голоса Vosk: каждый говорящий × скорость × два прогона."""
    for model_dir in sorted((voices / "vosk").glob("*/config.json")):
        config = json.loads(model_dir.read_text("utf-8"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from vosk_tts import Model, Synth

        synth = Synth(Model(model_path=str(model_dir.parent)))
        rate = int(config["audio"]["sample_rate"])
        for name, speaker_id in config["speaker_id_map"].items():
            for speed in SPEEDS:
                for draw in range(DRAWS):

                    def render(
                        text: str, sid: int = speaker_id, sp: float = speed, sy: Synth = synth, r: int = rate
                    ) -> np.ndarray:
                        return to_16k(sy.synth_audio(text, speaker_id=sid, speech_rate=sp), r)

                    yield f"vosk_{name}_{speed}_{draw}", render


def piper_voices(voices: Path) -> Iterator[tuple[str, Render]]:
    """Голоса Piper (*.onnx): скорость × два прогона с разной случайностью."""
    files = sorted(voices.glob("*.onnx"))
    if not files:
        return
    from piper import PiperVoice, SynthesisConfig

    for path in files:
        voice = PiperVoice.load(path)
        for speed in SPEEDS:
            for draw in range(DRAWS):
                config = SynthesisConfig(
                    length_scale=1 / speed, noise_scale=0.5 + 0.3 * draw, noise_w_scale=0.6 + 0.3 * draw
                )

                def render(text: str, c: SynthesisConfig = config, v: PiperVoice = voice) -> np.ndarray:
                    chunks = list(v.synthesize(text, syn_config=c))
                    pcm = b"".join(ch.audio_int16_bytes for ch in chunks)
                    return (
                        to_16k(np.frombuffer(pcm, dtype="<i2"), chunks[0].sample_rate)
                        if chunks
                        else np.zeros(0, np.int16)
                    )

                yield f"piper_{path.stem}_{speed}_{draw}", render


def write(path: Path, samples: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.astype("<i2").tobytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phrases", required=True, help="JSON-список фраз")
    args = parser.parse_args()
    phrases: list[str] = json.loads(args.phrases)
    texts = [
        (p, f"{p}{mark}", tag) for p in phrases for mark, tag in (("", "plain"), ("!", "excl"), ("?", "ask"))
    ]
    voices = [*silero_voices(args.voices), *vosk_voices(args.voices), *piper_voices(args.voices)]
    if not voices:
        sys.exit(f"нет голосов в {args.voices}: скачайте голоса в приложении (Настройки → Голос)")
    total, done = len(voices) * len(texts), 0
    for name, render in voices:
        for phrase, text, tag in texts:
            path = args.out / folder_name(phrase) / f"{name}_{tag}.wav"
            if not path.exists():
                try:
                    samples = trim(render(text))
                except Exception as error:  # noqa: BLE001 — один голос не должен рушить всё
                    print(
                        json.dumps(
                            {"log": f"{name}: «{text}» не синтезирован ({error})"}, ensure_ascii=False
                        ),
                        flush=True,
                    )
                    samples = np.zeros(0, np.int16)
                if len(samples) > RATE // 10:
                    write(path, samples)
            done += 1
            if done % 20 == 0 or done == total:
                print(
                    json.dumps({"stage": "синтетика", "done": done, "total": total}, ensure_ascii=False),
                    flush=True,
                )


if __name__ == "__main__":
    main()
