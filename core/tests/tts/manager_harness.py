"""Общая обвязка тестов менеджера голосов: поддельные фабрики, скачивания и файлы."""

import threading
from collections.abc import Callable
from pathlib import Path

from fakes.fake_events import RecordingSink
from fakes.fake_tts import FakeTTS
from smartesp.contracts import TextToSpeech
from smartesp.tts import VoiceManager

IRINA = "ru_RU-irina-medium"
Progress = Callable[[int, int | None], None] | None


def put_irina(home: Path) -> None:
    (home / "voices").mkdir(parents=True, exist_ok=True)
    (home / "voices" / f"{IRINA}.onnx").write_bytes(b"x")


def put_silero(home: Path) -> None:
    (home / "voices" / "silero").mkdir(parents=True, exist_ok=True)
    (home / "voices" / "silero" / "v5_ru.pt").write_bytes(b"x")


class Harness:
    """Менеджер с поддельными фабриками; запоминает сборки и вызовы on_ready."""

    def __init__(
        self,
        home: Path,
        download: Callable[..., None],
        *,
        make_tts: Callable[[], TextToSpeech] = FakeTTS,
        on_ready: Callable[[str, str], None] | None = None,
        **kwargs: object,
    ) -> None:
        self.ready: list[tuple[str, str]] = []
        self._make_tts = make_tts
        self._hook = on_ready
        self.built: list[tuple[str, str]] = []
        self.sink = RecordingSink()
        factories = {k: self._factory(k) for k in ("piper", "silero", "vosk")}
        self.manager = VoiceManager(
            home,
            factories,
            self._on_ready,
            events=self.sink,
            download=download,
            **kwargs,  # type: ignore[arg-type]
        )

    def _on_ready(self, tts: TextToSpeech, kind: str, voice: str) -> None:
        if self._hook is not None:
            self._hook(kind, voice)
        self.ready.append((kind, voice))

    def _factory(self, kind: str) -> Callable[[Path, str], TextToSpeech]:
        def build(path: Path, voice: str) -> TextToSpeech:
            self.built.append((kind, voice))
            return self._make_tts()

        return build

    def kinds(self, name: str) -> list[dict[str, object]]:
        return [data for kind, data in self.sink.events if kind == name]


def no_download(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
    raise AssertionError("скачивание не ожидалось")


def silero_download(kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
    assert progress is not None
    for done in range(0, 1001, 10):
        progress(done, 1000)
    put_silero(home)


class GatedDownload:
    """Поддельное скачивание: шлёт ход, пока не открыт затвор; помнит вызовы и обрывы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.started = threading.Event()
        self.gate = threading.Event()
        self.aborted = threading.Event()

    def __call__(self, kind: str, voice: str, home: Path, *, progress: Progress = None) -> None:
        assert progress is not None
        self.calls.append((kind, voice))
        self.started.set()
        try:
            while not self.gate.wait(0.01):
                progress(0, None)
        except Exception:
            self.aborted.set()
            raise
        put_silero(home)
