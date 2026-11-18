"""Подделка CorePort для тестов HTTP API."""

from __future__ import annotations

from typing import Any

from smartesp.contracts import ChangeResult, ExecutorError, VoiceNotDownloadedError


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
        "stt_ms": 120.0,
        "first_text_ms": None,
        "first_audio_ms": None,
    }


class FakeCore:
    def __init__(self) -> None:
        self.patches: list[dict[str, Any]] = []
        self.restarts = 0
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
                }
            ],
            "voice": self.voice_state,
            "applying": False,
            "restart_required": False,
        }

    def config(self) -> dict[str, Any]:
        return {
            "effective": {"tts": {"kind": "piper"}},
            "overridden": ["tts.kind"],
            "restart_sections": ["server", "stt", "arbitration"],
        }

    async def patch_config(self, patch: dict[str, Any]) -> ChangeResult:
        self.patches.append(patch)
        error = "неверная правка" if self.patch_status == "invalid" else ""
        return ChangeResult(len(self.patches), self.patch_status, error)

    async def models(self) -> list[dict[str, Any]]:
        if self.models_error:
            raise self.models_error
        return [{"name": "qwen", "size_bytes": 42}]

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


__all__ = ["FakeCore", "VoiceNotDownloadedError", "make_turn"]
