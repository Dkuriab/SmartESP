"""Схемы ответов и тел запросов HTTP API (по ним генерируется клиент интерфейса)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OllamaOut(BaseModel):
    """Состояние Ollama: доступна ли и какие модели загружены."""

    reachable: bool
    loaded: list[str]


class DeviceOut(BaseModel):
    """Колонка в сводке."""

    device_id: str
    name: str
    connected: bool
    remote: str  # адрес последней сессии «хост:порт»; колонку ещё не видели — ""
    fw: str
    last_seen: float | None = None


class VoiceStateOut(BaseModel):
    """Состояние нужного голоса; до первого открытия вида и голоса нет (null)."""

    kind: str | None
    voice: str | None
    state: Literal["ready", "downloading", "failed", "missing"]
    error: str | None = None


class StatusOut(BaseModel):
    """Сводка ядра."""

    version: str
    uptime_s: float
    state: Literal["warming", "ready", "stopping"]
    ollama: OllamaOut
    devices: list[DeviceOut]
    voice: VoiceStateOut
    applying: bool
    restart_required: bool


class ConfigOut(BaseModel):
    """Настройки: целиком, изменённые владельцем и разделы, требующие перезапуска."""

    effective: dict[str, Any]
    overridden: list[str]
    restart_sections: list[str]
    # итоговый промпт диспетчера с правилами включённых обработчиков; только для чтения
    dispatcher_prompt: str


class ErrorOut(BaseModel):
    """Тело ошибки HTTP."""

    detail: str


class ChangeOut(BaseModel):
    """Ответ на изменение."""

    change_id: int
    status: Literal["accepted", "restart_required", "invalid", "stopping"]
    error: str = ""


class ModelOut(BaseModel):
    """Модель Ollama."""

    name: str
    size_bytes: int


class VoiceOut(BaseModel):
    """Голос из каталога."""

    kind: str
    voice: str
    title: str
    size_mb: float
    downloaded: bool
    current: bool


class AnnotationOut(BaseModel):
    """Пометка этапа к реплике."""

    source: str
    text: str


class DelegationOut(BaseModel):
    """Передача задачи в ходе: от кого, кому, какая задача; auto — по фразе без вызова."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str = Field(alias="from")
    to: str
    task: str
    auto: bool = False


class TurnOut(BaseModel):
    """Данные события turn_finished."""

    turn_id: int | str
    device_id: str
    device_name: str
    text: str
    annotations: list[AnnotationOut]
    style: str
    answer: str
    status: Literal["ok", "error", "interrupted", "meaningless"]
    at: float
    stt_ms: float | None = None
    first_text_ms: float | None = None
    first_audio_ms: float | None = None
    path: list[str] = []  # id исполнителей хода по порядку
    delegations: list[DelegationOut] = []


class DownloadIn(BaseModel):
    """Тело запроса на скачивание голоса."""

    kind: str
    voice: str


class PreviewIn(BaseModel):
    """Тело запроса на пробное озвучивание."""

    kind: str
    voice: str
    style: str = "normal"
    text: str | None = None


class AccessOut(BaseModel):
    """Адреса для входа в интерфейс с других компьютеров сети (с токеном)."""

    urls: list[str]
