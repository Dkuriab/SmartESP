"""Менеджер голосов: открытие с фоновым скачиванием, запасной голос, повторы и образцы."""

import asyncio
import logging
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from smartesp.contracts import EventSink, TextToSpeech, VoiceNotDownloadedError

from ._fetcher import Download, SharedFetcher
from ._preview import PreviewCache, render_wav
from .catalog import catalog, is_downloaded, voice_path
from .download import VoiceDownloadError, download_voice

log = logging.getLogger(__name__)

Factory = Callable[[Path, str], TextToSpeech]
OnReady = Callable[[TextToSpeech, str, str], None]
Key = tuple[str, str]


async def _result(fut: "asyncio.Future[bool]") -> bool:
    """Ждёт итог, не отменяя его; отмена самого итога (не ждущего) — False."""
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        me = asyncio.current_task()
        if me is not None and me.cancelling():
            raise
        return False


class VoiceManager:
    """Держит текущий голос и приводит его к нужному.

    Состояние (state()) описывает нужный голос — последний, переданный в open():
    - ready — он текущий;
    - downloading — качается или ждёт повтора (error — текст последней ошибки);
    - failed — не удалось, повторов не будет;
    - missing — ещё не текущий и не качается (до open() или пока собирается).
    """

    def __init__(
        self,
        home: Path,
        factories: Mapping[str, Factory],
        on_ready: OnReady,
        *,
        events: EventSink | None = None,
        download: Download = download_voice,
        retry_delays_s: Sequence[float] = (30, 120, 300),
    ) -> None:
        """factories[вид](путь голоса, голос) собирает TTS; on_ready(tts, вид, голос) делает его текущим.

        retry_delays_s — паузы между повторами при retry=True; последняя повторяется.
        """
        self._home = home
        self._factories = factories
        self._on_ready = on_ready
        self._events = events
        self._fetcher = SharedFetcher(home, download, self._publish)
        self._delays = tuple(retry_delays_s) or (300.0,)
        self._current: Key | None = None
        self._current_tts: TextToSpeech | None = None
        self._wanted: Key | None = None
        self._state = "missing"
        self._error: str | None = None
        self._job: asyncio.Task[bool] | None = None
        self._job_retry = False
        self._outcome: asyncio.Future[bool] | None = None  # итог ближайшей попытки
        self._tasks: set[asyncio.Task[None]] = set()
        self._previews = PreviewCache()

    def state(self) -> dict[str, object]:
        """Возвращает {kind, voice, state, error} для нужного голоса."""
        kind, voice = self._wanted or (None, None)
        return {"kind": kind, "voice": voice, "state": self._state, "error": self._error}

    def catalog(self) -> list[dict[str, object]]:
        """Каталог голосов в форме API: {kind, voice, title, size_mb, downloaded, current}.

        current — голос, которым сейчас говорит ядро (может быть запасным, а не нужным).
        """
        return [
            {
                "kind": v.kind,
                "voice": v.voice,
                "title": v.title,
                "size_mb": v.size_mb,
                "downloaded": v.downloaded,
                "current": (v.kind, v.voice) == self._current,
            }
            for v in catalog(self._home)
        ]

    async def open(self, kind: str, voice: str, *, retry: bool) -> bool:
        """Делает голос текущим; True — получилось, False — нет или открытие отменено.

        Скачанный голос собирается и прогревается в потоке и уходит в on_ready.
        Нескачанный качается; пока его нет и текущего голоса нет совсем, в on_ready
        уходит первый скачанный из каталога. retry=False — одна попытка (изменение
        из приложения), retry=True — повторы, пока не получится (старт ядра).
        Итог каждой попытки — событие voice_ready (при retry=True и после неудач).

        Открытие другого голоса отменяет прежнее: оно возвращает False и не трогает
        on_ready. Открытие того же голоса, пока прежнее идёт, присоединяется к нему:
        retry=True включает повторы, retry=False ждёт итога ближайшей попытки.
        Отмена ждущего open() не отменяет само открытие — это делают новый open() и aclose().
        """
        key = (kind, voice)
        job = self._job
        if job is None or job.done() or self._wanted != key:
            job = self._start(key, retry)
        elif retry:
            self._job_retry = True
        if retry:
            return await _result(job)
        # одна попытка ждёт только итог ближайшей попытки, а не всё открытие:
        # присоединившийся retry=True не держит её на повторах
        assert self._outcome is not None
        return await _result(self._outcome)

    async def download(self, kind: str, voice: str) -> None:
        """Скачивает голос с событиями voice_download и итоговым voice_ready, не меняя текущий.

        Ошибка скачивания пробрасывается; отмена через aclose() — VoiceDownloadError.
        """
        task = asyncio.create_task(self._download_reporting(kind, voice))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        try:
            await task
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if me is not None and me.cancelling():
                raise
            raise VoiceDownloadError(f"Скачивание {kind}/{voice} отменено") from None

    async def preview(self, kind: str, voice: str, style: str, text: str) -> bytes:
        """Озвучивает образец; возвращает WAV 16 кГц, 16 бит, моно.

        Не скачан (в том числе ещё качается) — VoiceNotDownloadedError; неизвестный
        голос — ValueError; модель не дала звука — RuntimeError.
        Кроме текущего, в кеше держится один TTS — последний запрошенный.
        """
        key = (kind, voice)
        if not is_downloaded(kind, voice, self._home):
            raise VoiceNotDownloadedError(f"Голос {kind}/{voice} не скачан")
        tts = self._current_tts if self._current == key else None
        if tts is None:
            tts = await self._previews.get(key, self._construct)
        return await render_wav(tts, key, style, text)

    async def aclose(self) -> None:
        """Отменяет фоновые скачивания и повторы и дожидается их."""
        pending = [t for t in [self._job, *self._tasks] if t is not None]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending)
        self._settle(False)
        await self._fetcher.aclose()
        self._job = None
        self._previews.clear()

    # ---- внутреннее ----

    def _start(self, key: Key, retry: bool) -> asyncio.Task[bool]:
        """Запускает новое открытие вместо прежнего."""
        previous = self._job
        self._settle(False)
        self._wanted, self._job_retry, self._error = key, retry, None
        self._state = "ready" if self._current == key else "missing"
        self._outcome = asyncio.get_running_loop().create_future()
        job = asyncio.create_task(self._open(key, previous))
        job.add_done_callback(self._job_done)
        self._job = job
        if previous is not None:
            previous.cancel()
        return job

    def _job_done(self, job: asyncio.Task[bool]) -> None:
        ok = not job.cancelled() and job.exception() is None and job.result()
        if self._job is job:
            self._settle(ok)

    def _settle(self, ok: bool) -> None:
        if self._outcome is not None and not self._outcome.done():
            self._outcome.set_result(ok)

    async def _open(self, key: Key, previous: asyncio.Task[bool] | None) -> bool:
        if previous is not None:
            await asyncio.wait([previous])
        if self._current == key:
            self._state = "ready"
            return True
        try:
            downloaded = is_downloaded(*key, self._home)
        except ValueError as exc:
            self._fail(key, str(exc))
            return False
        if not downloaded and self._current is None:
            await self._fallback(key)
        return await self._attempts(key)

    async def _attempts(self, key: Key) -> bool:
        """Попытки скачать (если нужно) и включить голос; с повторами при retry."""
        attempt = 0
        while True:
            try:
                await self._attempt(key)
            except ValueError as exc:  # неизвестный голос: повторять бессмысленно
                self._fail(key, str(exc))
                return False
            except Exception as exc:  # noqa: BLE001 — любая ошибка попадает в состояние
                if not self._job_retry:
                    self._fail(key, str(exc))
                    return False
                await self._wait_retry(key, str(exc), attempt)
                attempt += 1
                continue
            self._state, self._error = "ready", None
            self._ready_event(key, ok=True, error=None)
            return True

    async def _wait_retry(self, key: Key, error: str, attempt: int) -> None:
        """Сообщает о неудачной попытке и ждёт паузу перед следующей."""
        delay = self._delays[min(attempt, len(self._delays) - 1)]
        log.warning("Голос %s/%s не готов (%s); повтор через %s с", *key, error, delay)
        self._error = error
        self._ready_event(key, ok=False, error=error)
        self._settle(False)
        self._outcome = asyncio.get_running_loop().create_future()
        await asyncio.sleep(delay)

    async def _attempt(self, key: Key) -> None:
        if not is_downloaded(*key, self._home):
            self._state = "downloading"
            await self._fetcher.fetch(*key)
            self._state = "missing"
        await self._activate(key)

    async def _fallback(self, wanted: Key) -> None:
        """Включает первый скачанный голос из каталога, пока нужного нет."""
        for info in catalog(self._home):
            key = (info.kind, info.voice)
            if not info.downloaded or key == wanted:
                continue
            try:
                await self._activate(key)
            except Exception:  # noqa: BLE001
                log.warning("Запасной голос %s/%s не включился", *key, exc_info=True)
                continue
            log.warning("Пока нет %s/%s, говорит запасной %s/%s", *wanted, *key)
            return

    async def _activate(self, key: Key) -> None:
        """Собирает и прогревает голос в потоке и отдаёт его в on_ready.

        Текущим голос считается только после того, как on_ready отработал без ошибки.
        """
        tts = self._previews.take(key)
        if tts is None:
            tts = await self._construct(key)
        warm_up = getattr(tts, "warm_up", None)
        if warm_up is not None:
            await warm_up()
        if self._job is not asyncio.current_task():
            raise asyncio.CancelledError  # открытие уже заменено новым
        self._on_ready(tts, *key)
        self._current, self._current_tts = key, tts

    async def _construct(self, key: Key) -> TextToSpeech:
        """Вызывает фабрику голоса в потоке: загрузка модели не блокирует цикл."""
        kind, voice = key
        factory = self._factories[kind]
        return await asyncio.to_thread(factory, voice_path(kind, voice, self._home), voice)

    async def _download_reporting(self, kind: str, voice: str) -> None:
        key = (kind, voice)
        if not is_downloaded(kind, voice, self._home):
            try:
                await self._fetcher.fetch(kind, voice)
            except Exception as exc:
                self._ready_event(key, ok=False, error=str(exc))
                raise
        self._ready_event(key, ok=True, error=None)

    def _fail(self, key: Key, error: str) -> None:
        log.warning("Голос %s/%s не включён: %s", *key, error)
        self._state, self._error = "failed", error
        self._ready_event(key, ok=False, error=error)

    def _ready_event(self, key: Key, *, ok: bool, error: str | None) -> None:
        self._publish("voice_ready", {"kind": key[0], "voice": key[1], "ok": ok, "error": error})

    def _publish(self, kind: str, data: dict[str, object]) -> None:
        if self._events is not None:
            self._events.publish(kind, data)
