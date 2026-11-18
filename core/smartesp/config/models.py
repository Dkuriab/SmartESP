"""Модели настроек ядра."""

from pydantic import BaseModel, Field, model_validator

DEFAULT_SYSTEM_PROMPT = (
    "Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
    "без разметки, списков и эмодзи — ответ будет озвучен. "
    "Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]. "
    "Во всех остальных случаях никаких меток не пиши."
)
DEFAULT_MODEL = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive"


class ServerConfig(BaseModel):
    """Адрес, на котором слушает сервер."""

    host: str = "0.0.0.0"
    port: int = 8765


class DeviceConfig(BaseModel):
    """Колонка: человекочитаемое имя."""

    name: str


class ArbitrationConfig(BaseModel):
    """Окно выбора колонки-победителя, мс."""

    window_ms: int = 300
    late_ms: int = 1500


class SttConfig(BaseModel):
    """Распознавание речи."""

    kind: str = "mlx_whisper"
    model: str = "mlx-community/whisper-large-v3-turbo"
    language: str = "ru"


class TtsConfig(BaseModel):
    """Синтез речи."""

    kind: str = "piper"
    voice: str = "ru_RU-irina-medium"


class ExecutorConfig(BaseModel):
    """Исполнитель (языковая модель); ровно один является входным."""

    id: str
    name: str
    kind: str = "ollama"
    model: str
    entry: bool = False
    system_prompt: str = ""
    keep_alive: str = "24h"


class StageConfig(BaseModel):
    """Этап обработки текста до исполнителя."""

    kind: str
    timeout_ms: int = 300


class HistoryConfig(BaseModel):
    """Ограничения истории диалога."""

    max_turns: int = 10
    max_age_s: int = 300


def _default_executors() -> list[ExecutorConfig]:
    return [
        ExecutorConfig(
            id="dispatcher",
            name="Диспетчер",
            model=DEFAULT_MODEL,
            entry=True,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
        )
    ]


class Config(BaseModel):
    """Корневые настройки ядра."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)
    arbitration: ArbitrationConfig = Field(default_factory=ArbitrationConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    executors: list[ExecutorConfig] = Field(default_factory=_default_executors)
    stages: list[StageConfig] = Field(default_factory=lambda: [StageConfig(kind="whisper_detect")])
    history: HistoryConfig = Field(default_factory=HistoryConfig)

    @model_validator(mode="after")
    def _check_single_entry(self) -> "Config":
        entries = [e for e in self.executors if e.entry]
        if len(entries) != 1:
            raise ValueError(f"нужен ровно один исполнитель с entry=true, найдено: {len(entries)}")
        return self

    def entry_executor(self) -> ExecutorConfig:
        """Возвращает входного исполнителя (единственного с entry=True)."""
        return next(e for e in self.executors if e.entry)
