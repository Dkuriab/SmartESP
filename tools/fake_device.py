"""Поддельная колонка: задаёт ядру вопрос из WAV-файла и отвечает на ходы ядра.

Подключается к ws://<host>:<port>/device и ведёт себя как прошивка (состояния
Idle → Listening → Waiting → Speaking): hello → wake → звук вопроса кадрами по
1024 байта (в реальном темпе) → utterance_end → ответ ядра «играется» столько,
сколько он звучит, → playback_done.

Протокол 3 (`--protocol 3`) добавляет ходы ядра:
- `announce{turn}` — из покоя «играет» сигнал «внимание» (как прошивка: сама и
  только приняв), ждёт reply_start → звук → reply_end, «играет» и шлёт playback_done{turn};
- `listen{turn}` — из покоя «слушает»: шлёт звук очередного `--answer-wav` и
  utterance_end{turn, vad}; ответы кончились — через 5 с utterance_end no_speech;
- не в покое (или с `--busy` — всегда) на announce/listen отвечает busy{turn}, без звука.

Колонка выходит, пробыв в покое `--linger` секунд (Ctrl+C — раньше). Печатает
сообщения ядра с отметкой времени и задержки, может сохранить ответы в WAV.

Запуск из корня репозитория:
    uv run --project core python tools/fake_device.py --wav core/tests/data/privet.wav
    uv run --project core python tools/fake_device.py --protocol 3 --wav q.wav --answer-wav a.wav
    uv run --project core python tools/fake_device.py --protocol 3 --linger 300   # ждать объявлений
WAV — 16 кГц, 16 бит, моно.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import wave
from pathlib import Path
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed

SAMPLE_RATE = 16000
FRAME_BYTES = 1024  # как у прошивки: 512 отсчётов s16le = 32 мс
REPLY_TIMEOUT_S = 60.0  # столько колонка в Waiting ждёт хоть какого-то кадра ядра (как прошивка)
NO_SPEECH_S = 5.0  # noSpeechTimeoutMs прошивки: listen без речи
POLL_S = 0.2


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


class FakeSpeaker:
    """Состояние поддельной колонки и реакция на кадры ядра."""

    def __init__(self, ws: ClientConnection, protocol: int, busy: bool, answers: list[bytes]) -> None:
        """ws — соединение; protocol — версия в hello; busy — на announce/listen всегда busy;
        answers — звук ответов на listen по порядку."""
        self.ws = ws
        self.protocol = protocol
        self.busy = busy
        self.answers = answers
        self.state = "idle"
        self.turn = 0
        self.started = self.since = self.heard = time.monotonic()  # heard — последний кадр ядра
        self.spoke_at = 0.0  # когда отправлен utterance_end (или пришёл announce)
        self.first_audio_at: float | None = None
        self.audio = bytearray()
        self.replies: list[bytes] = []
        self.task: asyncio.Task[None] | None = None  # отправка реплики или «игра» ответа

    def log(self, text: str) -> None:
        """Печатает строку с временем от подключения."""
        print(f"{(time.monotonic() - self.started) * 1000:8.0f} мс  {text}")

    def enter(self, state: str, turn: int | None = None) -> None:
        """Переходит в состояние; в покое ход сбрасывается."""
        self.state, self.since = state, time.monotonic()
        if turn is not None:
            self.turn = turn
        if state == "idle":
            self.turn = 0

    async def send(self, kind: str, **fields: Any) -> None:
        """Шлёт событие колонки и печатает его."""
        frame = json.dumps({"type": kind, **fields})
        await self.ws.send(frame)
        self.log(f"→ {frame}")

    def start(self, coro: Any) -> None:
        """Запускает фоновую работу хода (прежняя отменяется)."""
        self.stop_task()
        self.task = asyncio.create_task(coro)

    def stop_task(self) -> None:
        if self.task is not None and not self.task.done():
            self.task.cancel()
        self.task = None

    async def speak(self, pcm: bytes | None) -> None:
        """Listening: шлёт реплику в реальном темпе и utterance_end; без реплики — no_speech."""
        turn = self.turn
        if pcm is None:
            await asyncio.sleep(NO_SPEECH_S)
            await self.send("utterance_end", turn=turn, reason="no_speech")
            self.enter("idle")
            return
        for start in range(0, len(pcm), FRAME_BYTES):
            await self.ws.send(pcm[start : start + FRAME_BYTES])
            await asyncio.sleep(FRAME_BYTES / 2 / SAMPLE_RATE)  # реальный темп микрофона
        await self.send("utterance_end", turn=turn, reason="vad")
        self.spoke_at = time.monotonic()
        self.enter("waiting")
        self.log(f"реплика отправлена: {len(pcm)} байт")

    async def play(self) -> None:
        """Speaking после reply_end: доигрывает звук и шлёт playback_done."""
        seconds = len(self.audio) / 2 / SAMPLE_RATE
        started = self.first_audio_at or time.monotonic()
        await asyncio.sleep(max(0.0, started + seconds - time.monotonic()))
        await self.send("playback_done", turn=self.turn)
        self.enter("idle")

    def wake(self, pcm: bytes, turn: int) -> None:
        """Слово пробуждения: ход колонки turn, wake и реплика."""
        self.enter("listening", turn)
        self.start(self._wake_and_speak(pcm))

    async def _wake_and_speak(self, pcm: bytes) -> None:
        await self.send("wake", turn=self.turn, level=-30)
        await self.speak(pcm)

    # --- кадры ядра ---

    async def on_frame(self, frame: str | bytes) -> None:
        """Обрабатывает один кадр ядра."""
        self.heard = time.monotonic()
        if isinstance(frame, bytes):
            if self.state == "speaking":
                if self.first_audio_at is None:
                    self.first_audio_at = time.monotonic()
                    self.log(f"первый звук через {(self.first_audio_at - self.spoke_at) * 1000:.0f} мс")
                self.audio += frame
            return
        self.log(f"← {frame}")
        message = json.loads(frame)
        handler = _HANDLERS.get(message.get("type"))
        if handler is not None:
            await handler(self, message)

    async def on_stop_listening(self, m: dict[str, Any]) -> None:
        if m.get("turn") == self.turn and self.state == "listening":
            await self.end_by_server()
            self.enter("waiting")

    async def end_by_server(self) -> None:
        """Ядро закончило реплику раньше колонки: запись обрывается, utterance_end server."""
        self.stop_task()
        await self.send("utterance_end", turn=self.turn, reason="server")
        self.spoke_at = time.monotonic()

    async def on_reply_start(self, m: dict[str, Any]) -> None:
        if m.get("turn") == self.turn and self.state == "listening":
            await self.end_by_server()
        if m.get("turn") == self.turn and self.state in ("listening", "waiting"):
            self.log(f"reply_start через {(time.monotonic() - self.spoke_at) * 1000:.0f} мс")
            self.audio, self.first_audio_at = bytearray(), None
            self.enter("speaking")

    async def on_reply_end(self, m: dict[str, Any]) -> None:
        if m.get("turn") == self.turn and self.state == "speaking":
            self.replies.append(bytes(self.audio))
            self.log(f"звук ответа: {len(self.audio)} байт ({len(self.audio) / 2 / SAMPLE_RATE:.1f} с)")
            self.start(self.play())

    async def on_cancel(self, m: dict[str, Any]) -> None:
        if m.get("turn") == self.turn and self.state != "idle":
            self.stop_task()
            self.enter("idle")

    async def on_stop_playback(self, _m: dict[str, Any]) -> None:
        if self.state == "speaking":
            self.stop_task()
            self.enter("idle")

    async def on_announce(self, m: dict[str, Any]) -> None:
        turn = m.get("turn")
        if self.protocol >= 3 and (self.busy or self.state != "idle"):
            await self.send("busy", turn=turn)
        elif self.state == "idle":
            self.spoke_at = time.monotonic()
            self.enter("waiting", turn)
            self.log("♪ внимание (колонка приняла announce)")

    async def on_listen(self, m: dict[str, Any]) -> None:
        turn = m.get("turn")
        if self.protocol < 3:
            return  # прошивка v2 listen не знает
        if self.busy or self.state != "idle":
            await self.send("busy", turn=turn)
            return
        self.log(f"listen через {(time.monotonic() - self.since) * 1000:.0f} мс после покоя")
        self.enter("listening", turn)
        self.start(self.speak(self.answers.pop(0) if self.answers else None))

    def timed_out(self, linger: float) -> bool:
        """True — пора выходить: покой дольше linger или ответа ждём молча дольше REPLY_TIMEOUT_S.

        Как у прошивки: в Speaking таймаута нет (длинный ответ играется сколько звучит).
        """
        if self.state == "idle":
            return time.monotonic() - self.since >= linger
        waited = time.monotonic() - max(self.since, self.heard)
        if self.state == "waiting" and waited >= REPLY_TIMEOUT_S:
            self.log(f"ядро молчит {waited:.0f} с в состоянии {self.state}")
            return True
        return False


_HANDLERS = {
    "reply_start": FakeSpeaker.on_reply_start,
    "reply_end": FakeSpeaker.on_reply_end,
    "stop_listening": FakeSpeaker.on_stop_listening,
    "cancel_turn": FakeSpeaker.on_cancel,
    "stop_playback": FakeSpeaker.on_stop_playback,
    "announce": FakeSpeaker.on_announce,
    "listen": FakeSpeaker.on_listen,
}


async def run(url: str, args: argparse.Namespace) -> list[bytes]:
    """Подключается, задаёт вопрос (если есть) и обслуживает ходы ядра; возвращает звуки ответов."""
    answers = [read_pcm(path) for path in args.answer_wav]
    async with connect(url, max_size=None) as ws:
        speaker = FakeSpeaker(ws, args.protocol, args.busy, answers)
        await speaker.send("hello", device_id=args.device_id, fw="fake", protocol=args.protocol)
        if args.wav is not None:
            speaker.wake(read_pcm(args.wav), args.turn)
        try:
            while not speaker.timed_out(args.linger):
                try:
                    frame = await asyncio.wait_for(ws.recv(), POLL_S)  # отмена recv безопасна
                except TimeoutError:
                    continue
                await speaker.on_frame(frame)
        except ConnectionClosed:
            speaker.log("ядро закрыло соединение")
        finally:
            speaker.stop_task()
        return speaker.replies


def save(out: Path, replies: list[bytes]) -> None:
    """Первый ответ — в out, следующие — в out-2.wav, out-3.wav…"""
    for index, pcm in enumerate(replies, start=1):
        path = out if index == 1 else out.with_name(f"{out.stem}-{index}{out.suffix}")
        write_wav(path, pcm)
        print(f"ответ сохранён: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Поддельная колонка SmartESP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--wav", type=Path, help="вопрос: WAV 16 кГц, 16 бит, моно (без него — только ждать)")
    parser.add_argument("--device-id", default="fake")
    parser.add_argument("--turn", type=int, default=1, help="номер хода вопроса")
    parser.add_argument("--protocol", type=int, default=2, choices=(2, 3))
    parser.add_argument(
        "--answer-wav", type=Path, action="append", default=[], help="ответ на listen (можно несколько)"
    )
    parser.add_argument("--busy", action="store_true", help="на announce/listen всегда busy (протокол 3)")
    parser.add_argument("--linger", type=float, default=3.0, help="сколько секунд покоя до выхода")
    parser.add_argument("--out", type=Path, help="куда сохранить ответы (WAV)")
    args = parser.parse_args()
    if args.busy and args.protocol < 3:
        parser.error("--busy нужен протокол 3")
    url = f"ws://{args.host}:{args.port}/device"
    try:
        replies = asyncio.run(run(url, args))
    except KeyboardInterrupt:
        return
    if args.out is not None:
        save(args.out, replies)


if __name__ == "__main__":
    main()
