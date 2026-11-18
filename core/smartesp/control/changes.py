"""Очередь изменений настроек: сравнение разделов и применение по одному."""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Mapping
from typing import Any, cast

from smartesp.contracts import ChangeResult, ConfigStore, EventSink, Section, VoicePort

_log = logging.getLogger(__name__)

RESTART_SECTIONS = ("server", "stt", "arbitration")
TTS_SECTION = "tts"
_NOT_SECTIONS = (*RESTART_SECTIONS, TTS_SECTION)  # их не собирают через Section


class ChangeQueue:
    """Принимает правки настроек и применяет их строго по одной в фоновой задаче.

    Применение одной правки:
    1. правка сливается заново поверх уже применённых (поэтому два быстрых PATCH
       не затирают друг друга);
    2. собираются ВСЕ изменившиеся разделы на лету (Section.build), по очереди;
    3. если изменился tts — voices.open(kind, voice, retry=False);
    4. подменяются все собранные части (swap), затем освобождаются старые (release);
    5. store.save(new) и событие change_applied(ok=True).

    Сбой на шагах 1–3 — ничего не подменено, собранные части освобождаются, файл не
    трогается, change_applied(ok=False, error). Голос при этом может уже смениться
    сам (его подменяет менеджер голосов), но tts открывается последним, после всех
    сборок, так что сбой сборки до него не доходит. Сбой swap (договор: не падает)
    оставляет уже подменённые части подменёнными, файл не трогается. Сбой release
    только пишется в журнал: изменение уже применено.

    Разделы из RESTART_SECTIONS не собираются, а только записываются; после записи
    такой правки restart_required = True до перезапуска процесса.
    """

    def __init__(
        self,
        store: ConfigStore,
        sections: Mapping[str, Section],
        *,
        voices: VoicePort,
        events: EventSink,
    ) -> None:
        self._store = store
        self._sections = dict(sections)
        self._voices = voices
        self._events = events
        self._queue: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._busy = False
        self._closed = False
        self.restart_required = False

    @property
    def applying(self) -> bool:
        """True, пока применяется правка или в очереди есть ждущие."""
        return self._busy or not self._queue.empty()

    def submit(self, change_id: int, patch: dict[str, Any]) -> ChangeResult:
        """Проверяет правку и ставит её в очередь; не ждёт применения."""
        if self._closed:
            return ChangeResult(change_id, "invalid", "ядро останавливается")
        try:
            _, changed = self._diff(patch)
        except ValueError as error:
            return ChangeResult(change_id, "invalid", str(error))
        self._queue.put_nowait((change_id, copy.deepcopy(patch)))
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="config-changes")
        if any(name in RESTART_SECTIONS for name in changed):
            return ChangeResult(change_id, "restart_required")
        return ChangeResult(change_id, "accepted")

    async def aclose(self) -> None:
        """Останавливает очередь: текущая правка отменяется (без записи и события), ждущие отбрасываются."""
        self._closed = True
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()

    # ---- внутреннее ----

    def _diff(self, patch: dict[str, Any]) -> tuple[Any, list[str]]:
        """Новые настройки и разделы, которые правка меняет; ValueError — правка неверна."""
        old = self._store.merge({})  # пустая правка — текущие записанные настройки
        new = self._store.merge(patch)
        changed = [
            name
            for name in self._store.effective()
            if self._store.section(old, name) != self._store.section(new, name)
        ]
        return new, changed

    async def _run(self) -> None:
        while True:
            change_id, patch = await self._queue.get()
            self._busy = True
            try:
                await self._apply(change_id, patch)
            finally:
                self._busy = False

    async def _apply(self, change_id: int, patch: dict[str, Any]) -> None:
        changed: list[str] = []
        try:
            new, changed = self._diff(patch)
            await self._apply_live(new, changed)
            self._store.save(new)
        except Exception as error:
            _log.warning("Изменение %s не применено: %s", change_id, error, exc_info=True)
            self._announce(change_id, changed, str(error) or type(error).__name__)
            return
        if any(name in RESTART_SECTIONS for name in changed):
            self.restart_required = True
        _log.info("Изменение %s применено: %s", change_id, ", ".join(changed) or "без изменений")
        self._announce(change_id, changed, None)

    async def _apply_live(self, new: Any, changed: list[str]) -> None:
        live = [name for name in changed if name in self._sections and name not in _NOT_SECTIONS]
        built = await self._build_all(new, live)
        try:
            if TTS_SECTION in changed:
                await self._open_voice(new)
        except BaseException:
            await self._release_all(built)
            raise
        old = {name: self._sections[name].swap(part) for name, part in built.items()}
        await self._release_all(old)

    async def _build_all(self, new: Any, names: list[str]) -> dict[str, object]:
        """Собирает части по очереди; сбой — освобождает уже собранные и пробрасывает."""
        built: dict[str, object] = {}
        try:
            for name in names:
                built[name] = await self._sections[name].build(new)
        except BaseException:
            await self._release_all(built)
            raise
        return built

    async def _open_voice(self, new: Any) -> None:
        tts = cast(dict[str, object], self._store.section(new, TTS_SECTION))
        kind, voice = str(tts["kind"]), str(tts["voice"])
        if not await self._voices.open(kind, voice, retry=False):
            error = self._voices.state().get("error")
            raise RuntimeError(str(error) if error else f"Голос {kind}/{voice} не включился")

    async def _release_all(self, parts: Mapping[str, object | None]) -> None:
        """Освобождает части разделов; сбой одной только пишется в журнал."""
        for name, part in parts.items():
            release = self._sections[name].release
            if part is None or release is None:
                continue
            try:
                await release(part)
            except Exception:
                _log.warning("Раздел %s: часть не освобождена", name, exc_info=True)

    def _announce(self, change_id: int, sections: list[str], error: str | None) -> None:
        data: dict[str, object] = {
            "change_id": change_id,
            "ok": error is None,
            "error": error,
            "sections": sections,
        }
        self._events.publish("change_applied", data)
