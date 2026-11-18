"""Поддельная колонка: задаёт ядру вопрос из WAV-файла и ждёт ответ.

Подключается к ws://<host>:<port>/device как колонка протокола v2: hello → wake →
звук вопроса кадрами по 1024 байта (в реальном темпе) → utterance_end. Печатает
сообщения ядра, задержку до reply_start и первого звука, может сохранить ответ в WAV.

Запуск из корня репозитория:
    uv run --project core python tools/fake_device.py --wav core/tests/data/privet.wav
WAV — 16 кГц, 16 бит, моно.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path

from websockets.asyncio.client import ClientConnection, connect

SAMPLE_RATE = 16000
FRAME_BYTES = 1024  # как у прошивки: 512 отсчётов s16le = 32 мс
REPLY_TIMEOUT_S = 60.0


def read_pcm(path: Path) -> bytes:
    """Читает PCM из WAV и проверяет формат (16 кГц, 16 бит, моно)."""
    with wave.open(str(path), "rb") as wav:
        if (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) != (SAMPLE_RATE, 2, 1):
            raise SystemExit(f"{path}: нужен WAV 16 кГц, 16 бит, моно")
        return wav.readframes(wav.getnframes())


def write_wav(path: Path, pcm: bytes) -> None:
    """Сохраняет ответ ядра (PCM 16 кГц s16le) в WAV."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)


async def ask(url: str, pcm: bytes, device_id: str, turn: int) -> bytes:
    """Задаёт один вопрос и возвращает звук ответа."""
    async with connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "hello", "device_id": device_id, "fw": "fake", "protocol": 2}))
        await ws.send(json.dumps({"type": "wake", "turn": turn, "level": -30}))
        for start in range(0, len(pcm), FRAME_BYTES):
            await ws.send(pcm[start : start + FRAME_BYTES])
            await asyncio.sleep(FRAME_BYTES / 2 / SAMPLE_RATE)  # реальный темп микрофона
        await ws.send(json.dumps({"type": "utterance_end", "turn": turn, "reason": "vad"}))
        asked_at = time.monotonic()
        print(f"вопрос отправлен: {len(pcm)} байт")
        return await receive_reply(ws, turn, asked_at)


async def receive_reply(ws: ClientConnection, turn: int, asked_at: float) -> bytes:
    """Читает кадры ядра до reply_end хода turn; печатает сообщения и задержки."""
    audio = bytearray()
    async with asyncio.timeout(REPLY_TIMEOUT_S):
        async for frame in ws:
            ms = (time.monotonic() - asked_at) * 1000
            if isinstance(frame, bytes):
                if not audio:
                    print(f"первый звук через {ms:.0f} мс")
                audio += frame
                continue
            print(f"{ms:6.0f} мс  {frame}")
            message = json.loads(frame)
            if message.get("type") in ("reply_end", "cancel_turn") and message.get("turn") == turn:
                break
    seconds = len(audio) / 2 / SAMPLE_RATE
    print(f"звук ответа: {len(audio)} байт ({seconds:.1f} с)")
    return bytes(audio)


def main() -> None:
    parser = argparse.ArgumentParser(description="Поддельная колонка SmartESP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--wav", type=Path, required=True, help="вопрос: WAV 16 кГц, 16 бит, моно")
    parser.add_argument("--device-id", default="fake")
    parser.add_argument("--turn", type=int, default=1)
    parser.add_argument("--out", type=Path, help="куда сохранить ответ (WAV)")
    args = parser.parse_args()
    url = f"ws://{args.host}:{args.port}/device"
    audio = asyncio.run(ask(url, read_pcm(args.wav), args.device_id, args.turn))
    if args.out is not None:
        write_wav(args.out, audio)
        print(f"ответ сохранён: {args.out}")


if __name__ == "__main__":
    main()
