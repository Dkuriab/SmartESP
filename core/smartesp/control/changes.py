"""Очередь изменений настроек: сравнение разделов и применение по одному."""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Callable, Coroutine, Mapping, Sequence
from typing import Any, cast

from smartesp.contracts import ChangeResult, ConfigStore, EventSink, Section, VoicePort

from .jobs import Job, Rebuild, settle

_log = logging.getLogger(__name__)

RESTART_SECTIONS = ("server", "stt", "arbitration")
TTS_SECTION = "tts"
_NOT_SECTIONS = (*RESTART_SECTIONS, TTS_SECTION)  # их не собирают через Section
STOPPING = "ядро останавливается"


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
    трогается, change_applied(ok=False, error). tts открывается последним, после
    всех сборок. Если голос не открылся, в фоне снова открывается прежний голос
    (retry=True), чтобы менеджер голосов вернулся к записанным настройкам; следующая
    правка tts сначала отменяет этот возврат, чтобы он не перебил новый голос.
    Сбой swap (договор: не падает) оставляет уже подменённые части подменёнными,
    файл не трогается. Сбой release только пишется в журнал: изменение уже применено.
    Сбой save после подмены — части уже новые, а файл старый: громкая запись в
    журнал и change_applied(ok=False, error="применено, но не сохранено: …").

    release может ждать конца звучащих ходов — тогда следующая правка ждёт тоже.

    Разделы из RESTART_SECTIONS не собираются, а только записываются; после записи
    такой правки restart_required = True до перезапуска процесса.

    Один и тот же Section под несколькими именами (исполнитель зависит и от
    executors, и от stages) собирается, подменяется и освобождается один раз.
    validate(настройки) проверяет правку целиком (например, известны ли виды
    stt, tts, исполнителей) до постановки в очередь и ещё раз перед применением;
    ValueError — правка неверна и не записывается.

    rebuild — та же очередь без правки: пересобрать разделы по записанным
    настройкам (например, сменились инструменты коннекторов). Так пересборка не
    гоняется с правкой: она идёт после её записи и берёт уже новые настройки.
    """

    def __init__(
        self,
        store: ConfigStore,
        sections: Mapping[str, Section],
        *,
        voices: VoicePort,
        events: EventSink,
        validate: Callable[[Any], None] | None = None,
    ) -> None:
        self._store = store
        self._validate = validate
        self._sections = dict(sections)
        self._voices = voices
        self._events = events
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._background: set[asyncio.Task[None]] = set()
        self._restore: asyncio.Task[None] | None = None  # возврат прежнего голоса после сбоя
        self._busy = False
        self.closed = False
        self.restart_required = False

    @property
    def applying(self) -> bool:
        """True, пока применяется правка или в очереди есть ждущие."""
        return self._busy or not self._queue.empty()

    def submit(self, change_id: int, patch: dict[str, Any]) -> ChangeResult:
        """Проверяет правку и ставит её в очередь; не ждёт применения.

        После aclose — status "stopping", правка не принимается.
        """
        if self.closed:
            return ChangeResult(change_id, "stopping", STOPPING)
        try:
            _, _, changed = self._diff(patch)
        except ValueError as error:
            return ChangeResult(change_id, "invalid", str(error))
        self._enqueue((change_id, copy.deepcopy(patch)))
        if any(name in RESTART_SECTIONS for name in changed):
            return ChangeResult(change_id, "restart_required")
        return ChangeResult(change_id, "accepted")

    async def rebuild(self, names: Sequence[str]) -> None:
        """Пересобирает разделы names по записанным настройкам в очереди (после идущих правок).

        Собирает, подменяет и освобождает, как правка, но без записи и события.
        Ошибка сборки пробрасывается; после aclose — RuntimeError, ждущая — отмена.
        """
        if self.closed:
            raise RuntimeError(STOPPING)
        done = asyncio.get_running_loop().create_future()
        self._enqueue(Rebuild(tuple(names), done))
        await done

    async def aclose(self) -> None:
        """Останавливает очередь и фоновые задачи.

        Текущая правка отменяется (без записи и события), ждущие отбрасываются.
        """
        self.closed = True
        tasks = [t for t in [self._worker, *self._background] if t is not None]
        self._worker = None
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        while not self._queue.empty():
            job = self._queue.get_nowait()
            if isinstance(job, Rebuild):
                job.done.cancel()

    # ---- внутреннее ----

    def _enqueue(self, job: Job) -> None:
        self._queue.put_nowait(job)
        if self._worker is None:
            self._worker = asyncio.create_task(self._run(), name="config-changes")

    def _diff(self, patch: dict[str, Any]) -> tuple[Any, Any, list[str]]:
        """Старые и новые настройки и изменённые разделы; ValueError — правка неверна."""
        old = self._store.merge({})  # пустая правка — текущие записанные настройки
        new = self._store.merge(patch)
        if self._validate is not None:
            self._validate(new)
        changed = [
            name
            for name in self._store.effective()
            if self._store.section(old, name) != self._store.section(new, name)
        ]
        return old, new, changed

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            self._busy = True
            try:
                if isinstance(job, Rebuild):
                    await self._rebuild(job)
                else:
                    await self._apply(*job)
            except Exception:  # очередь не должна умирать ни от чего
                _log.error("Очередь изменений: сбой", exc_info=True)
            finally:
                self._busy = False

    async def _rebuild(self, job: Rebuild) -> None:
        """Пересборка по записанным настройкам; итог — в job.done (отмена очереди — его отмена)."""
        try:
            config = self._store.merge({})
            await self._apply_live(config, config, list(job.names))
        except Exception as error:
            settle(job.done, error)
            return
        except BaseException:
            job.done.cancel()
            raise
        settle(job.done, None)

    async def _apply(self, change_id: int, patch: dict[str, Any]) -> None:
        changed: list[str] = []
        try:
            old, new, changed = self._diff(patch)
            await self._apply_live(old, new, changed)
        except Exception as error:
            _log.warning("Изменение %s не применено: %s", change_id, error, exc_info=True)
            self._announce(change_id, changed, _text(error))
            return
        try:
            self._store.save(new)
        except Exception as error:
            _log.error("Изменение %s применено, но НЕ сохранено в файл", change_id, exc_info=True)
            self._announce(change_id, changed, f"применено, но не сохранено: {_text(error)}")
            return
        if any(name in RESTART_SECTIONS for name in changed):
            self.restart_required = True
        _log.info("Изменение %s применено: %s", change_id, ", ".join(changed) or "без изменений")
        self._announce(change_id, changed, None)

    async def _apply_live(self, old: Any, new: Any, changed: list[str]) -> None:
        built = await self._build_all(new, self._live_names(changed))
        try:
            if TTS_SECTION in changed:
                await self._open_voice(old, new)
        except BaseException:
            await self._release_all(built)
            raise
        previous = {name: self._sections[name].swap(part) for name, part in built.items()}
        await self._release_all(previous)

    def _live_names(self, changed: list[str]) -> list[str]:
        """Изменившиеся разделы на лету; у общего Section — только первое имя."""
        names: list[str] = []
        seen: set[int] = set()
        for name in changed:
            section = self._sections.get(name)
            if section is None or name in _NOT_SECTIONS or id(section) in seen:
                continue
            seen.add(id(section))
            names.append(name)
        return names

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

    async def _open_voice(self, old: Any, new: Any) -> None:
        await self._cancel_restore()  # иначе запоздалый возврат перебьёт этот голос
        kind, voice = self._voice(new)
        if await self._voices.open(kind, voice, retry=False):
            return
        error = self._voices.state().get("error")
        self._restore = self._spawn(self._restore_voice(*self._voice(old)))
        raise RuntimeError(str(error) if error else f"Голос {kind}/{voice} не включился")

    def _voice(self, config: Any) -> tuple[str, str]:
        tts = cast(dict[str, object], self._store.section(config, TTS_SECTION))
        return str(tts["kind"]), str(tts["voice"])

    async def _restore_voice(self, kind: str, voice: str) -> None:
        """Возвращает менеджер голосов к записанному голосу (с повторами, как при старте)."""
        try:
            if not await self._voices.open(kind, voice, retry=True):
                _log.warning("Прежний голос %s/%s не вернулся", kind, voice)
        except Exception:
            _log.warning("Прежний голос %s/%s не вернулся", kind, voice, exc_info=True)

    async def _cancel_restore(self) -> None:
        """Отменяет ещё идущий возврат прежнего голоса и ждёт его.

        Не начавшийся возврат не зовёт open вовсе; начавшийся перебивается
        следующим open другого голоса в менеджере голосов.
        """
        restore, self._restore = self._restore, None
        if restore is not None and not restore.done():
            restore.cancel()
            await asyncio.gather(restore, return_exceptions=True)

    def _spawn(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

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
        try:
            self._events.publish("change_applied", data)
        except Exception:
            _log.error("Изменение %s: событие change_applied не отправлено", change_id, exc_info=True)


def _text(error: Exception) -> str:
    return str(error) or type(error).__name__
