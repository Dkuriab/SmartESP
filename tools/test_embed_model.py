"""Тесты tools/embed_model.py и замер модели слова на синтетике.

Запуск из корня репозитория:
    uv run --project core pytest tools/test_embed_model.py

Замеру нужны pymicro-features и ai-edge-litert (в ядро не входят) и голоса в
SMARTESP_HOME или ~/SmartEsp/voices; без них он пропускается. Звук для замера
синтезирует ядро (uv run --project core) во временную папку теста.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EMBED = ROOT / "tools" / "embed_model.py"
MANIFEST = ROOT / "tools" / "models" / "miranda" / "miranda.json"
MODEL = MANIFEST.parent / "miranda.tflite"
MODEL_DATA = ROOT / "firmware" / "SmartEsp" / "src" / "wake_word" / "ModelData.cpp"
CUTOFF = 0.9


def embed(out: Path, *extra: str) -> str:
    """Запускает embed_model.py на «Миранде» и возвращает текст ModelData.cpp."""
    subprocess.run([sys.executable, str(EMBED), str(MANIFEST), str(out), *extra], check=True)
    return out.read_text(encoding="utf-8")


def field(text: str, name: str) -> str:
    """Значение константы `name` из ModelData.cpp."""
    match = re.search(rf"\b{name}(?:\[\])? = (.+?);", text, re.S)
    assert match, f"нет {name}"
    return match.group(1)


def model_bytes(text: str) -> bytes:
    """Байты массива модели из ModelData.cpp."""
    return bytes(int(b, 16) for b in re.findall(r"0x([0-9a-f]{2})", field(text, "WAKE_MODEL_DATA")))


def test_embed_writes_model_and_settings(tmp_path: Path) -> None:
    text = embed(tmp_path / "ModelData.cpp", "--cutoff", str(CUTOFF))
    assert "alignas(16) const uint8_t WAKE_MODEL_DATA[]" in text
    assert model_bytes(text) == MODEL.read_bytes()
    assert int(field(text, "WAKE_MODEL_SIZE")) == MODEL.stat().st_size
    assert field(text, "WAKE_MODEL_CUTOFF") == "0.9f"
    assert int(field(text, "WAKE_MODEL_WINDOW")) == 5
    assert int(field(text, "WAKE_MODEL_ARENA_SIZE")) == 26080
    assert field(text, "WAKE_MODEL_WORD") == '"Миранда"'


def test_cutoff_defaults_to_manifest(tmp_path: Path) -> None:
    text = embed(tmp_path / "ModelData.cpp")
    assert field(text, "WAKE_MODEL_CUTOFF") == "0.5f"


def test_committed_model_data_is_up_to_date(tmp_path: Path) -> None:
    text = embed(tmp_path / "ModelData.cpp", "--cutoff", str(CUTOFF))
    assert MODEL_DATA.read_text(encoding="utf-8") == text


# ---------- замер: вероятность модели на синтетике ----------

VOICES = [("silero", "xenia"), ("silero", "aidar"), ("vosk", "male_0")]
WAKE_PHRASE = "Миранда."
OTHER_PHRASE = "Включи, пожалуйста, свет на кухне."
SAMPLE_RATE = 16000
STEP_SAMPLES = 160
FLOAT32_SCALE = 0.0390625

# Синтез в процессе ядра: голоса — его зависимости, а не этого окружения.
SYNTH = """
import asyncio, json, os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from smartesp.tts import SileroTTS, VoskTTS, voice_path
home = Path(os.environ.get("SMARTESP_HOME") or Path.home() / "SmartEsp")
async def render(tts, text):
    return b"".join([chunk async for chunk in tts.synthesize(text, "normal")])
for kind, voice, text, out in json.loads(sys.argv[2]):
    path = voice_path(kind, voice, home)
    tts = SileroTTS(path, voice) if kind == "silero" else VoskTTS(path, voice)
    Path(out).write_bytes(asyncio.run(render(tts, text)))
"""


def voices_home() -> Path:
    return Path(os.environ.get("SMARTESP_HOME") or Path.home() / "SmartEsp") / "voices"


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str, str], bytes]:
    """PCM 16 кГц каждой фразы каждым голосом (в папке теста, не в ~/SmartEsp)."""
    pytest.importorskip("pymicro_features")
    pytest.importorskip("ai_edge_litert")
    home = voices_home()
    if not (home / "silero").is_dir() or not (home / "vosk").is_dir():
        pytest.skip(f"нет голосов в {home}")
    folder = tmp_path_factory.mktemp("clips")
    jobs = [
        (kind, voice, text, str(folder / f"{kind}_{voice}_{i}.raw"))
        for kind, voice in VOICES
        for i, text in enumerate((WAKE_PHRASE, OTHER_PHRASE))
    ]
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    command = ["uv", "run", "--project", str(ROOT / "core"), "python", "-c", SYNTH]
    subprocess.run([*command, str(ROOT / "core"), json.dumps(jobs)], check=True, env=env, cwd=ROOT)
    return {(kind, voice, text): Path(out).read_bytes() for kind, voice, text, out in jobs}


def window_means(pcm: bytes) -> list[float]:
    """Средние вероятности по окну, как в прошивке (WakeWord): признаки микрофронтенда,
    квантование по входу модели, вызов каждые 3 кадра, вероятность = uint8 / 255."""
    import numpy as np
    from ai_edge_litert.interpreter import Interpreter
    from pymicro_features import MicroFrontend

    window = json.loads(MANIFEST.read_text(encoding="utf-8"))["micro"]["sliding_window_size"]
    interpreter = Interpreter(model_path=str(MODEL))
    interpreter.allocate_tensors()
    input_info = interpreter.get_input_details()[0]
    output_info = interpreter.get_output_details()[0]
    scale, zero_point = input_info["quantization"]
    stride = int(input_info["shape"][1])

    silence = bytes(SAMPLE_RATE)  # 0,5 с тишины до и после фразы
    audio = silence + pcm + silence + silence
    frontend = MicroFrontend()
    frames: list[np.ndarray] = []
    probabilities: list[float] = []
    means: list[float] = []
    step_bytes = STEP_SAMPLES * 2
    for start in range(0, len(audio) - step_bytes + 1, step_bytes):
        features = frontend.process_samples(audio[start : start + step_bytes]).features
        if not features:
            continue
        values = np.round(np.array(features) / FLOAT32_SCALE)  # uint16, как в прошивке
        quantized = np.clip(np.round(values * FLOAT32_SCALE / scale) + zero_point, -128, 127)
        frames.append(quantized.astype(np.int8))
        if len(frames) < stride:
            continue
        interpreter.set_tensor(input_info["index"], np.stack(frames).reshape(input_info["shape"]))
        frames.clear()
        interpreter.invoke()
        probabilities.append(float(interpreter.get_tensor(output_info["index"]).item()) / 255)
        if len(probabilities) >= window:
            means.append(sum(probabilities[-window:]) / window)
    return means


@pytest.mark.parametrize(("kind", "voice"), VOICES)
def test_model_hears_wake_word(clips: dict[tuple[str, str, str], bytes], kind: str, voice: str) -> None:
    best = max(window_means(clips[(kind, voice, WAKE_PHRASE)]))
    print(f"{kind}/{voice} «{WAKE_PHRASE}»: максимум среднего {best:.3f}")
    assert best > CUTOFF


@pytest.mark.parametrize(("kind", "voice"), VOICES)
def test_model_ignores_other_speech(clips: dict[tuple[str, str, str], bytes], kind: str, voice: str) -> None:
    best = max(window_means(clips[(kind, voice, OTHER_PHRASE)]))
    print(f"{kind}/{voice} «{OTHER_PHRASE}»: максимум среднего {best:.3f}")
    assert best < CUTOFF
