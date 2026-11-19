"""Договор: пульт ядра — изменения настроек, сводка и то, что нужно API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ChangeResult:
    """Ответ на изменение: номер, статус и текст ошибки.

    status: accepted, restart_required, invalid (правка неверна) или stopping
    (ядро останавливается, правка не принята).
    """

    change_id: int
    status: str
    error: str = ""


@dataclass(frozen=True)
class Section:
    """Сборщик одного раздела настроек, применяемого на лету.

    build — собирает новую часть из настроек целиком (может долго: качать, греть);
    swap — подменяет часть и возвращает старую (или None);
    release — освобождает старую часть после подмены (например, выгружает модель).

    Правила для release:
    - его могут вызвать и для части, которую так и не подменили (собрана, но
      правка не удалась); такая часть может совпадать с живой (та же модель);
    - он не должен освобождать то, чем ещё пользуется живая часть или звучащий
      ход (например, не выгружать модель, если у живой части та же);
    - он МОЖЕТ ждать конца звучащих ходов; очередь изменений ждёт вместе с ним,
      и следующая правка начнётся только после него.
    """

    build: Callable[[Any], Awaitable[object]]
    swap: Callable[[object], object | None]
    release: Callable[[object], Awaitable[None]] | None = None


class ConfigStore(Protocol):
    """Хранилище настроек; реализует ConfigFile."""

    def effective(self) -> dict[str, Any]:
        """Возвращает настройки целиком, в форме config.yaml."""
        ...

    def overridden(self) -> list[str]:
        """Возвращает ключи через точку, которые поменял владелец."""
        ...

    def merge(self, patch: dict[str, Any]) -> Any:
        """Сливает правку с текущими настройками, ничего не пишет; неверная — ValueError."""
        ...

    def save(self, config: Any) -> None:
        """Записывает настройки (результат merge) в файл и делает их текущими."""
        ...

    def section(self, config: Any, name: str) -> object:
        """Возвращает значение раздела верхнего уровня — для сравнения до и после правки."""
        ...


class VoicePort(Protocol):
    """То, что пульт берёт у менеджера голосов."""

    def catalog(self) -> list[dict[str, object]]:
        """Возвращает каталог: {kind, voice, title, size_mb, downloaded, current}."""
        ...

    def state(self) -> dict[str, object]:
        """Возвращает {kind, voice, state, error} для нужного голоса."""
        ...

    async def open(self, kind: str, voice: str, *, retry: bool) -> bool:
        """Делает голос текущим; True — получилось."""
        ...

    async def download(self, kind: str, voice: str) -> None:
        """Скачивает голос, не меняя текущий; ошибка пробрасывается."""
        ...

    async def preview(self, kind: str, voice: str, style: str, text: str) -> bytes:
        """Озвучивает образец в WAV; голос не скачан — VoiceNotDownloadedError."""
        ...


class CorePort(Protocol):
    """Всё, что HTTP API берёт у ядра; реализует control.Core."""

    async def status(self) -> dict[str, Any]:
        """Возвращает сводку: version, uptime_s, state, ollama, devices, voice, applying, restart_required,
        executors ([{id, ready, error}] — итог фонового прогрева исполнителей),
        connectors (как в connectors())."""
        ...

    def connectors(self) -> list[dict[str, Any]]:
        """Возвращает MCP-коннекторы: [{id, name, state, tools, error}] в порядке настроек."""
        ...

    def config(self) -> dict[str, Any]:
        """Возвращает {effective, overridden, restart_sections, dispatcher_prompt, executor_prompts}."""
        ...

    async def patch_config(self, patch: dict[str, Any]) -> ChangeResult:
        """Проверяет правку и ставит её в очередь; отвечает сразу, не дожидаясь применения."""
        ...

    async def models(self) -> list[dict[str, Any]]:
        """Возвращает модели Ollama: [{name, size_bytes, supports_tools}]; нет Ollama — ExecutorError."""
        ...

    def voices(self) -> list[dict[str, Any]]:
        """Возвращает каталог голосов в форме API."""
        ...

    async def download_voice(self, kind: str, voice: str) -> ChangeResult:
        """Запускает скачивание голоса в фоне и сразу отвечает accepted; голоса нет в каталоге — invalid."""
        ...

    async def preview(self, kind: str, voice: str, style: str, text: str) -> bytes:
        """Озвучивает образец в WAV; голос не скачан — VoiceNotDownloadedError."""
        ...

    def turns(self, limit: int) -> list[dict[str, object]]:
        """Возвращает последние ходы, от новых к старым."""
        ...

    def request_restart(self) -> None:
        """Просит ядро перезапуститься."""
        ...
