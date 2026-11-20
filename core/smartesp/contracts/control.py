"""Договор: пульт ядра — изменения настроек, сводка и то, что нужно API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from .ask import Answer, Question


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
    release — освобождает старую часть после подмены (например, выгружает модель);
    refresh — сборка для пересборки по тем же записанным настройкам (без правки), например
      без прогрева моделей; None — как build.

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
    refresh: Callable[[Any], Awaitable[object]] | None = None


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

    def connector_settings(self) -> dict[str, dict[str, Any]]:
        """Возвращает объявленное коннекторами по id: {settings: [{key, title, type, hint, value}],
        note, example}; непустое значение секрета скрыто («•••»)."""
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
        connectors ([{id, name, state, tools, error}] — без settings, сводку опрашивают часто)."""
        ...

    def connectors(self) -> list[dict[str, Any]]:
        """Возвращает MCP-коннекторы: [{id, name, state, tools, error, settings, note, example}] в порядке
        настроек; settings, note, example — объявленное коннектором (ConfigStore.connector_settings)."""
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

    def request_stop(self) -> None:
        """Просит ядро честно остановиться и выйти с кодом 0 (без перезапуска)."""
        ...

    def info(self) -> dict[str, Any]:
        """Возвращает {version, uptime_s, state, data_dir} — сведения о самом ядре."""
        ...

    async def unload_model(self, name: str) -> None:
        """Выгружает модель из памяти Ollama.

        Модели нет среди загруженных — ModelNotLoadedError; Ollama недоступна — ExecutorError.
        """
        ...

    async def ask(self, question: Question) -> Answer:
        """Ход через API текстом: тот же путь, что с колонки, но без звука; ответ текстом.

        Ядро не готово или останавливается — AskUnavailable.
        """
        ...

    async def ask_voice(self, audio: bytes, person: str, source: str) -> Answer:
        """Ход через API голосом: звук (OGG/Opus, WAV) → распознавание → как ask.

        Звук не разобрать — AudioUndecodable; нет программы разбора или ядро не готово — AskUnavailable.
        """
        ...
