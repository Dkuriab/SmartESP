"""Схемы ответов и тел запросов HTTP API (по ним генерируется клиент интерфейса)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class OllamaOut(BaseModel):
    """Состояние Ollama: доступна ли и какие модели загружены."""

    reachable: bool
    loaded: list[str]


class UpdateOut(BaseModel):
    """Обновление колонки по воздуху: what — firmware | model; state — sent (команда ушла) | progress |
    done (записано, колонка перезагружается) | failed; error — busy, download, size, hash, write, storage."""

    what: str
    state: str
    done: int
    total: int
    error: str
    at: float  # секунды Unix последнего изменения


class DeviceOut(BaseModel):
    """Колонка в сводке."""

    device_id: str
    name: str
    connected: bool
    remote: str  # адрес последней сессии «хост:порт»; колонку ещё не видели — ""
    fw: str
    last_seen: float | None = None
    protocol: int = 0  # версия протокола последней сессии; 0 — колонку ещё не видели
    update: UpdateOut | None = None  # последнее обновление по воздуху (протокол 4, прошивка 0.5.0+)


class VoiceStateOut(BaseModel):
    """Состояние нужного голоса; до первого открытия вида и голоса нет (null)."""

    kind: str | None
    voice: str | None
    state: Literal["ready", "downloading", "failed", "missing"]
    error: str | None = None


class ExecutorStateOut(BaseModel):
    """Итог фонового прогрева исполнителя (кроме входного): ready=False — модель недоступна."""

    id: str
    ready: bool
    error: str | None = None


class SuggestionOut(BaseModel):
    """Предложение клиента дописать value в настройку-список key («Добавить»); text — для людей."""

    key: str
    value: str
    text: str


class ConnectorOut(BaseModel):
    """Коннектор или клиент ядра: состояние, инструменты (как их видит модель; только у готового), ошибка.

    kind: mcp — коннектор с инструментами; client — программа-клиент ядра (бот Telegram): у неё
    журнал (последние строки) и предложения «Добавить» вместо инструментов.
    """

    id: str
    name: str
    state: Literal["starting", "ready", "failed", "disabled"]
    tools: list[str]
    error: str = ""  # текст последней ошибки; пусто — ошибки нет
    kind: Literal["mcp", "client"] = "mcp"
    log: list[str] = Field(default_factory=list[str])
    suggestions: list[SuggestionOut] = Field(default_factory=list[SuggestionOut])


class ConnectorSettingOut(BaseModel):
    """Настройка, объявленная коннектором (smartesp.json): ключ env, подпись, тип, значение.

    type: text — строка, path — путь (/ или ~/), list — папки «имя=путь;…», pairs — «ключ=значение;…»,
    secret — скрытое (значение «•••», если задано; назад «•••» — не менять), flag — «1» или пусто.
    """

    key: str
    title: str
    type: Literal["text", "path", "list", "secret", "flag", "pairs"]
    hint: str = ""
    value: str = ""


class ConnectorDetailOut(ConnectorOut):
    """Коннектор в GET /connectors: ещё и настройки, которые можно менять из интерфейса.

    note и example — пояснение коннектора для панели и пример для config.yaml (нет — "").
    """

    settings: list[ConnectorSettingOut] = Field(default_factory=list[ConnectorSettingOut])
    note: str = ""
    example: str = ""


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
    # исполнители, чей фоновый прогрев закончился; ещё греется или входной — его здесь нет
    executors: list[ExecutorStateOut] = Field(default_factory=list[ExecutorStateOut])
    connectors: list[ConnectorOut] = Field(default_factory=list[ConnectorOut])  # в порядке настроек


class ConfigOut(BaseModel):
    """Настройки: целиком, изменённые владельцем и разделы, требующие перезапуска."""

    effective: dict[str, Any]
    overridden: list[str]
    restart_sections: list[str]
    # итоговый промпт диспетчера с правилами включённых обработчиков; только для чтения
    dispatcher_prompt: str
    # итоговые промпты всех исполнителей по id (свой + обработчики + правило передачи)
    executor_prompts: dict[str, str]


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
    supports_tools: bool  # умеет вызывать инструменты (без них — не передаёт задачи)


class CloudModelOut(BaseModel):
    """Модель облачного сервиса (цены — доллары за 1 млн токенов; неизвестно — null)."""

    id: str
    name: str
    tools: bool  # умеет вызывать инструменты
    prompt_price: float | None
    completion_price: float | None


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


class ToolUseOut(BaseModel):
    """Вызов инструмента в ходе: кто вызвал, коннектор ("" — неизвестен), инструмент, удался ли."""

    executor: str
    connector: str
    tool: str
    ok: bool


class TurnOut(BaseModel):
    """Данные события turn_finished."""

    turn_id: int | str
    device_id: str
    device_name: str
    text: str
    annotations: list[AnnotationOut]
    style: str
    answer: str
    status: Literal["ok", "error", "interrupted", "meaningless", "undelivered"]
    at: float
    stt_ms: float | None = None
    first_text_ms: float | None = None
    first_audio_ms: float | None = None
    path: list[str] = []  # id исполнителей хода по порядку
    delegations: list[DelegationOut] = []
    tools: list[ToolUseOut] = []  # законченные вызовы инструментов по порядку
    # страховка честности: повторный прогон после ложного «сделала» или честная фраза вместо ответа
    guard: Literal["retried", "fallback"] | None = None
    # слово, прослушивание после вопроса, ядро само, вопрос через API
    origin: Literal["wake", "listen", "core", "api"] = "wake"
    source: str = ""  # ход через API: откуда вопрос ("telegram"); иначе пусто
    person: str = ""  # ход через API: кто спрашивает; иначе пусто
    kind: Literal["turn", "announcement"] = "turn"  # ход разговора или объявление ядра
    # мягкое прерывание: ответ уступил результату отложенной задачи / ход продолжает прерванный ответ
    interruption: Literal["paused", "resumed"] | None = None


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


PERSON_PATTERN = r"^[^\x00-\x1f\x7f]*$"  # без управляющих символов: имя — одна строка промпта
Person = Annotated[str, StringConstraints(strip_whitespace=True, max_length=64, pattern=PERSON_PATTERN)]
Source = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,32}$")]


class AskIn(BaseModel):
    """Вопрос через API текстом: текст, кто спрашивает ("" — неизвестно) и откуда (для ленты)."""

    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8000)]
    person: Person = ""
    source: Source = "api"


class AskOut(BaseModel):
    """Ответ на вопрос через API: текст ответа и номер хода в ленте."""

    answer: str
    turn_id: str


class PlayOut(BaseModel):
    """Файл на колонке начал играть; итог придёт событием playback_finished."""

    status: Literal["started"] = "started"


class StopOut(BaseModel):
    """Остановка файла: stopped=False — файл не играл."""

    stopped: bool


class CoreInfoOut(BaseModel):
    """Ядро: версия, время работы, состояние, порт сервера из настроек и папка данных."""

    version: str
    uptime_s: float
    state: Literal["warming", "ready", "stopping"]
    port: int
    data_dir: str


MODEL_PATTERN = r"^[^\x00-\x1f\x7f]+$"  # имя модели Ollama: одна строка без управляющих символов


class UnloadIn(BaseModel):
    """Какую модель выгрузить из памяти Ollama (имя как в status.ollama.loaded)."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=MODEL_PATTERN)]
