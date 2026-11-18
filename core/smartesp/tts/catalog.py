"""Каталог голосов: что бывает, где лежит и что уже скачано."""

import re
from pathlib import Path

from smartesp.contracts import VoiceInfo

SILERO_FILE = "v5_ru.pt"
VOSK_DIR = "vosk-model-tts-ru-0.9-multi"
IRINA = "ru_RU-irina-medium"
# Имя Piper-голоса: <locale>-<name>-<quality>
PIPER_NAME = re.compile(r"^[a-z]{2,3}_[A-Z]{2}-[A-Za-z0-9_]+-[a-z_]+$")

# (вид, голос, подпись, размер в МБ); файл Silero и папка Vosk общие на несколько голосов
_BUILTIN: list[tuple[str, str, str, int]] = [
    ("piper", IRINA, "Piper: Ирина", 63),
    ("silero", "xenia", "Silero: Ксения", 145),
    ("silero", "baya", "Silero: Бая", 145),
    ("silero", "kseniya", "Silero: Ксения (мягкий)", 145),
    ("vosk", "female_0", "Vosk: женский 0", 900),
    ("vosk", "female_1", "Vosk: женский 1", 900),
    ("vosk", "female_2", "Vosk: женский 2", 900),
]


def _known(kind: str) -> list[str]:
    return [v for k, v, _, _ in _BUILTIN if k == kind]


def voice_path(kind: str, voice: str, home: Path) -> Path:
    """Возвращает путь голоса: .onnx (Piper), .pt (Silero) или папку модели (Vosk).

    Неизвестный вид или голос — ValueError со списком известных.
    """
    voices = home / "voices"
    if kind == "piper":
        if voice not in _known("piper") and not PIPER_NAME.match(voice):
            raise ValueError(f"Неизвестный голос Piper {voice!r}: нужен вид <locale>-<name>-<quality>")
        return voices / f"{voice}.onnx"
    if kind not in ("silero", "vosk") or voice not in _known(kind):
        known = ", ".join(f"{k}/{v}" for k, v, _, _ in _BUILTIN)
        raise ValueError(f"Неизвестный голос {kind}/{voice}. Известные: {known}")
    if kind == "silero":
        return voices / "silero" / SILERO_FILE
    return voices / "vosk" / VOSK_DIR


def is_downloaded(kind: str, voice: str, home: Path) -> bool:
    """Скачан ли голос: существует ли его итоговый файл или папка."""
    return voice_path(kind, voice, home).exists()


def catalog(home: Path) -> list[VoiceInfo]:
    """Список голосов: piper (в т. ч. лишние voices/*.onnx), затем silero и vosk."""
    builtin = [VoiceInfo(k, v, title, size, is_downloaded(k, v, home)) for k, v, title, size in _BUILTIN]
    extra: list[VoiceInfo] = []
    voices = home / "voices"
    if voices.is_dir():
        extra = [
            VoiceInfo("piper", f.stem, f"Piper: {f.stem}", 0, True)
            for f in sorted(voices.glob("*.onnx"))
            if f.stem not in _known("piper")
        ]
    piper = [v for v in builtin if v.kind == "piper"]
    rest = [v for v in builtin if v.kind != "piper"]
    return piper + extra + rest
