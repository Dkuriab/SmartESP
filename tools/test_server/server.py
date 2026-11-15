#!/usr/bin/env python3
"""Тестовый сервер SmartESP: проверка прошивки без нейросети.

Эхо: принимает вопрос и после utterance_end отправляет его же обратно как ответ.
Протокол — docs/superpowers/specs/2026-11-15-firmware-design.md, раздел 7.

    python3 server.py [--port 8765] [--long] [--odd]

Команды в консоли:
    v 0.3                    громкость
    t wake|error|thinking    встроенный тон
    s                        stop_playback
    l                        stop_listening для текущего хода
"""

import argparse
import asyncio
import json
import math
import struct
import sys

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2


class Device:
    """Состояние одного подключённого ESP."""

    def __init__(self, websocket, args):
        self.ws = websocket
        self.args = args
        self.turn = 0
        self.question = bytearray()
        self.collecting = False
        self.reply_task = None
        self.reply_turn = None

    async def send(self, message):
        print(f"→ {json.dumps(message)}")
        await self.ws.send(json.dumps(message))

    def cancel_reply(self, turn=None):
        if self.reply_task and not self.reply_task.done() and (turn is None or turn == self.reply_turn):
            self.reply_task.cancel()
            print(f"   ответ на ход {self.reply_turn} прерван")

    def reply_audio(self):
        if self.args.long:
            # 60 с тона 440 Гц: больше очереди ESP (30 с) — проверка переполнения.
            samples = (int(8000 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)) for i in range(SAMPLE_RATE * 60))
            return b"".join(struct.pack("<h", s) for s in samples)
        return bytes(self.question)

    async def reply(self, turn):
        audio = self.reply_audio()
        chunk = 4095 if self.args.odd else 4096
        await self.send({"type": "reply_start", "turn": turn})
        for start in range(0, len(audio), chunk):
            part = audio[start:start + chunk]
            await self.ws.send(part)
            await asyncio.sleep(len(part) / BYTES_PER_SECOND)  # реальный темп
        await self.send({"type": "reply_end", "turn": turn})
        print(f"   ответ на ход {turn}: {len(audio) / BYTES_PER_SECOND:.1f} с")

    async def on_text(self, message):
        kind = message.get("type")
        turn = message.get("turn")
        if kind == "wake":
            self.turn = turn
            self.question = bytearray()
            self.collecting = True
        elif kind == "utterance_end":
            self.collecting = False
            print(f"   вопрос: {len(self.question) / BYTES_PER_SECOND:.1f} с")
            if message.get("reason") != "no_speech":
                self.cancel_reply()
                self.reply_turn = turn
                self.reply_task = asyncio.create_task(self.reply(turn))
        elif kind == "barge_in":
            self.cancel_reply(turn)

    async def run(self):
        async for data in self.ws:
            if isinstance(data, bytes):
                if self.collecting:
                    self.question.extend(data)
                continue
            print(f"← {data}")
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                print("   (не JSON)")
                continue
            await self.on_text(message)


DEVICE = None


async def handle(websocket, args):
    global DEVICE
    if websocket.request.path != "/device":
        await websocket.close(code=1008, reason="unknown path")
        return
    print(f"ESP подключился: {websocket.remote_address}")
    DEVICE = Device(websocket, args)
    try:
        await DEVICE.run()
    except ConnectionClosed:
        pass
    finally:
        DEVICE.cancel_reply()
        print("ESP отключился")
        DEVICE = None


async def console():
    loop = asyncio.get_running_loop()
    while True:
        raw = await loop.run_in_executor(None, sys.stdin.readline)
        if raw == "":
            await asyncio.Future()  # ввод закрыт (EOF) — консоли нет, сервер работает дальше
        line = raw.strip()
        if not line:
            continue
        if DEVICE is None:
            print("ESP не подключён")
            continue
        parts = line.split()
        try:
            if parts[0] == "v":
                await DEVICE.send({"type": "volume", "value": float(parts[1])})
            elif parts[0] == "t":
                await DEVICE.send({"type": "tone", "name": parts[1]})
            elif parts[0] == "s":
                DEVICE.cancel_reply()
                await DEVICE.send({"type": "stop_playback"})
            elif parts[0] == "l":
                await DEVICE.send({"type": "stop_listening", "turn": DEVICE.turn})
            else:
                print("команды: v <0..1> | t wake|error|thinking | s | l")
        except (IndexError, ValueError):
            print("команды: v <0..1> | t wake|error|thinking | s | l")


async def main():
    sys.stdout.reconfigure(line_buffering=True)  # лог виден сразу, даже при выводе в файл
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--long", action="store_true", help="ответ — 60 с тона (проверка переполнения очереди)")
    parser.add_argument("--odd", action="store_true", help="звук кусками по 4095 байт (проверка нечётных кусков)")
    args = parser.parse_args()

    async with serve(lambda ws: handle(ws, args), "0.0.0.0", args.port):
        print(f"Сервер слушает ws://0.0.0.0:{args.port}/device")
        await console()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
