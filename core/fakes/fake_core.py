"""Подделка CorePort для тестов HTTP API."""

from __future__ import annotations

from typing import Any

from smartesp.contracts import (
    Answer,
    ChangeResult,
    ExecutorError,
    ModelNotLoadedError,
    Question,
    VoiceNotDownloadedError,
)


def make_turn(turn_id: int) -> dict[str, object]:
    """Данные события turn_finished для тестов."""
    return {
        "turn_id": turn_id,
        "device_id": "d1",
        "device_name": "Кухня",
        "text": "привет",
        "annotations": [{"source": "stage", "text": "заметка"}],
        "style": "normal",
        "answer": "Здравствуйте",
        "status": "ok",
        "at": 1700000000.5,
        "stt_ms": 120.0,
        "first_text_ms": None,
        "first_audio_ms": None,
    }


class FakeCore:
    def __init__(self) -> None:
        self.patches: list[dict[str, Any]] = []
        self.restarts = 0
        self.stops = 0
        self.loaded = ["qwen3:8b", "hf.co/user/model:Q4"]  # модели в памяти Ollama
        self.unloaded: list[str] = []
        self.unload_error: ExecutorError | None = None
        self.voice_state: dict[str, object] = {
            "kind": "piper",
            "voice": "irina",
            "state": "ready",
            "error": None,
        }
        self.patch_status = "accepted"
        self.download_status = "accepted"
        self.preview_error: Exception | None = None
        self.models_error: ExecutorError | None = None
        self.previews: list[tuple[str, str, str, str]] = []
        self.turn_items = [make_turn(i) for i in (3, 2, 1)]
        self.connector_items: list[dict[str, Any]] = [
            {
                "id": "notes",
                "name": "Заметки",
                "state": "ready",
                "tools": ["note_add"],
                "error": "",
                "kind": "mcp",
                "log": [],
                "suggestions": [],
                "settings": [],
                "note": "",
                "example": "",
            },
            {
                "id": "weather",
                "name": "Погода",
                "state": "failed",
                "tools": [],
                "error": "упал",
                "kind": "mcp",
                "log": [],
                "suggestions": [],
                "settings": [
                    {
                        "key": "WEATHER_PLACE",
                        "title": "Город",
                        "type": "text",
                        "hint": "Москва",
                        "value": "Тверь",
                    },
                    {"key": "WEATHER_PIN", "title": "Пин", "type": "secret", "hint": "", "value": "•••"},
                ],
                "note": "",
                "example": "",
            },
        ]
        self.questions: list[Question] = []  # вопросы /ask
        self.voices_asked: list[tuple[bytes, str, str]] = []  # (звук, человек, источник) /ask/voice
        self.ask_error: Exception | None = None  # бросается из ask и ask_voice

    async def status(self) -> dict[str, Any]:
        return {
            "version": "0.1.0",
            "uptime_s": 12.5,
            "state": "ready",
            "ollama": {"reachable": True, "loaded": ["m1"]},
            "devices": [
                {
                    "device_id": "d1",
                    "name": "Кухня",
                    "connected": True,
                    "remote": "10.0.0.5:1234",
                    "fw": "1.0",
                    "last_seen": 1.0,
                    "protocol": 3,
                    "update": None,
                    "volume": 50,
                }
            ],
            "voice": self.voice_state,
            "applying": False,
            "restart_required": False,
            "executors": [{"id": "big", "ready": False, "error": "нет модели"}],
            "connectors": [
                {k: v for k, v in c.items() if k not in ("settings", "note", "example")}
                for c in self.connector_items
            ],
        }

    def connectors(self) -> list[dict[str, Any]]:
        return list(self.connector_items)

    def config(self) -> dict[str, Any]:
        return {
            "effective": {"tts": {"kind": "piper"}},
            "overridden": ["tts.kind"],
            "restart_sections": ["server", "stt", "arbitration"],
            "dispatcher_prompt": "Ты помощник.",
            "executor_prompts": {"dispatcher": "Ты помощник.", "big": "Ты большая модель."},
        }

    async def patch_config(self, patch: dict[str, Any]) -> ChangeResult:
        self.patches.append(patch)
        error = "неверная правка" if self.patch_status == "invalid" else ""
        return ChangeResult(len(self.patches), self.patch_status, error)

    async def models(self) -> list[dict[str, Any]]:
        if self.models_error:
            raise self.models_error
        return [{"name": "qwen", "size_bytes": 42, "supports_tools": True}]

    async def cloud_models(self) -> list[dict[str, Any]]:
        if self.models_error:
            raise self.models_error
        return [
            {
                "id": "google/gemini-2.5-flash",
                "name": "Gemini 2.5 Flash",
                "tools": True,
                "prompt_price": 0.3,
                "completion_price": 2.5,
            },
        ]

    def voices(self) -> list[dict[str, Any]]:
        return [
            {
                "kind": "piper",
                "voice": "irina",
                "title": "Ирина",
                "size_mb": 60.0,
                "downloaded": True,
                "current": True,
            }
        ]

    async def download_voice(self, kind: str, voice: str) -> ChangeResult:
        error = "Неизвестный голос" if self.download_status == "invalid" else ""
        return ChangeResult(7, self.download_status, error)

    async def preview(self, kind: str, voice: str, style: str, text: str) -> bytes:
        self.previews.append((kind, voice, style, text))
        if self.preview_error:
            raise self.preview_error
        return b"RIFFfake"

    def turns(self, limit: int) -> list[dict[str, object]]:
        return self.turn_items[:limit]

    def request_restart(self) -> None:
        self.restarts += 1

    def request_stop(self) -> None:
        self.stops += 1

    def info(self) -> dict[str, Any]:
        return {"version": "0.1.0", "uptime_s": 12.5, "state": "ready", "data_dir": "/tmp/smartesp"}

    async def unload_model(self, name: str) -> None:
        if self.unload_error:
            raise self.unload_error
        if name not in self.loaded:
            raise ModelNotLoadedError(name)
        self.unloaded.append(name)

    async def ask(self, question: Question) -> Answer:
        self.questions.append(question)
        if self.ask_error:
            raise self.ask_error
        return Answer(f"Ответ на «{question.text}»", f"api{len(self.questions)}")

    async def ask_voice(self, audio: bytes, person: str, source: str) -> Answer:
        self.voices_asked.append((audio, person, source))
        if self.ask_error:
            raise self.ask_error
        return Answer("Голос услышан", f"api{len(self.voices_asked)}")


__all__ = ["FakeCore", "VoiceNotDownloadedError", "make_turn"]
