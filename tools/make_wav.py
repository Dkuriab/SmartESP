"""Озвучивает фразу голосом Silero в WAV 16 кГц для fake_device.py.

Запуск из корня репозитория (ядро — виртуальный uv-проект, поэтому путь к нему
добавляется в sys.path, а голоса берутся из SMARTESP_HOME или ~/SmartEsp):
    uv run --project core python tools/make_wav.py "Привет, как дела?" q.wav
    uv run --project core python tools/make_wav.py "текст" q.wav --voice silero/xenia
Голос — silero/<имя> (скачанный в SMARTESP_HOME); PCM 16 кГц, 16 бит, моно.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))

from smartesp.tts import SileroTTS, voice_path  # noqa: E402

SAMPLE_RATE = 16000


async def synthesize(text: str, kind: str, voice: str, home: Path) -> bytes:
    """Озвучивает текст и склеивает куски PCM."""
    if kind != "silero":
        raise SystemExit("make_wav.py умеет только голоса silero/<имя>")
    try:
        path = voice_path(kind, voice, home)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if not path.exists():
        raise SystemExit(f"Модель голоса не найдена: {path}. Скачайте голос в интерфейсе или ядром.")
    tts = SileroTTS(path, voice)
    return b"".join([chunk async for chunk in tts.synthesize(text, "normal")])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("text", help="фраза для озвучки")
    parser.add_argument("out", type=Path, help="куда записать WAV")
    parser.add_argument("--voice", default="silero/xenia", help="вид/имя, по умолчанию silero/xenia")
    args = parser.parse_args()
    kind, _, voice = args.voice.partition("/")
    home = Path(os.environ.get("SMARTESP_HOME") or Path.home() / "SmartEsp")
    pcm = asyncio.run(synthesize(args.text, kind, voice, home))
    if not pcm:
        raise SystemExit("синтез ничего не дал")
    with wave.open(str(args.out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    print(f"{args.out}: {len(pcm) / 2 / SAMPLE_RATE:.1f} с")


if __name__ == "__main__":
    main()
