"""Модели настроек ядра."""

from pydantic import BaseModel, Field, field_validator, model_validator

from smartesp.contracts import Reasoning

from .connectors import ConnectorConfig, default_connectors, overlay_connectors

DEFAULT_SYSTEM_PROMPT = (
    "Тебя зовут Кузя. Ты голосовой помощник умной колонки дома, твой ответ озвучивается. Правила:\n"
    "1. Отвечай по-русски и коротко: обычно одно предложение, не больше трёх. Без разметки, списков"
    " и эмодзи.\n"
    "2. Заметки, списки, таймеры, погода, расчёты, музыка, поиск в интернете: если для этого есть"
    " инструмент — сначала вызови его, потом отвечай по его ответу. Про заметки и списки не отвечай"
    " по памяти: каждый раз смотри инструментом и называй, что там есть.\n"
    "3. «Сделала», «записала», «включила» говори, только если инструмент это сделал; ответил ошибкой —"
    " так и скажи. Просят что-то сделать (свет, техника, покупки), а инструмента для этого нет —"
    " скажи: «Этого я пока не умею». Никогда не говори, что это уже сделано или включено.\n"
    "4. Время, погоду, числа, новости и состояние дома бери только из инструментов и справки."
    " Не знаешь — так и скажи, не выдумывай.\n"
    "5. В справке есть время, что сейчас в работе и твои навыки. Говори о них, только когда"
    " об этом спросили.\n"
    "6. Не задавай вопросов в конце ответа и не предлагай помощь. Спрашивай, только если без уточнения"
    " просьбу не выполнить. Пример: «Привет, как дела?» — «Привет! Всё хорошо.»\n"
    "7. Разговор, шутки и общие знания — не действия: на них отвечай сам.\n"
    "8. Человек прощается или говорит, что больше ничего не нужно, — ответь одним словом: «Пока!»"
)
# «Нет доступа» — только для действий и данных без инструмента: это правило ядра (network/rules.py);
# на разговор и общие знания отвечать как обычно.
# 2 — в config.yaml только изменения владельца; 3 — умолчание tts стало silero;
# 4 — в сохранённый список stages добавлен обработчик clock (по умолчанию включён);
# 5 — так же добавлен обработчик system (что в работе и какие навыки)
CONFIG_VERSION = 5
# замер волны 3: честнее всех и первый текст p90 < 1 с — только с рассуждением «low»
DEFAULT_MODEL = "gpt-oss:20b"
DEFAULT_REASONING: Reasoning = "low"
BIG_WHEN = "сложные вопросы: рассуждения, расчёты, подробные объяснения, знания, которых может не быть у тебя"
BIG_SYSTEM_PROMPT = (
    "Ты отвечаешь голосом через колонку: по-русски, без разметки и списков, связно, до 6–8 предложений."
)


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

    kind: str = "silero"
    voice: str = "xenia"


class DelegateLink(BaseModel):
    """Связь: исполнитель может передать задачу исполнителю to, когда подходит условие when."""

    to: str
    when: str = ""


class ExecutorConfig(BaseModel):
    """Исполнитель (языковая модель); ровно один является входным."""

    id: str
    name: str
    kind: str = "ollama"
    model: str
    entry: bool = False
    system_prompt: str = ""
    keep_alive: str = "24h"
    # рассуждение перед ответом: off/low/medium/high (как передаётся модели — решает исполнитель)
    reasoning: Reasoning = "off"
    description: str = ""
    delegates: list[DelegateLink] = Field(default_factory=list)


class StageConfig(BaseModel):
    """Этап обработки текста до исполнителя."""

    kind: str
    timeout_ms: int = 300
    # только для whisper_detect: отвечать тише на шёпот. По умолчанию нет: ни один голос
    # не умеет настоящий шёпот, «тихо» — просто громкость ниже; шёпот всё равно распознаётся
    quiet_reply: bool = False


class HistoryConfig(BaseModel):
    """Ограничения истории диалога."""

    max_turns: int = 10
    max_age_s: int = 300


class SpeechConfig(BaseModel):
    """Речь по инициативе ядра: объявления и слушание после вопроса."""

    proactive: bool = True
    listen_after_question: bool = True


def _default_executors() -> list[ExecutorConfig]:
    return [
        ExecutorConfig(
            id="dispatcher",
            name="Диспетчер",
            model=DEFAULT_MODEL,
            reasoning=DEFAULT_REASONING,
            entry=True,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            delegates=[DelegateLink(to="big", when=BIG_WHEN)],
        ),
        ExecutorConfig(
            id="big",
            name="Большая модель",
            model="deepseek-r1:8b",
            description="большая модель: рассуждения, расчёты, подробные объяснения, знания",
            system_prompt=BIG_SYSTEM_PROMPT,
        ),
    ]


class Config(BaseModel):
    """Корневые настройки ядра."""

    version: int = CONFIG_VERSION
    server: ServerConfig = Field(default_factory=ServerConfig)
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)
    arbitration: ArbitrationConfig = Field(default_factory=ArbitrationConfig)
    stt: SttConfig = Field(default_factory=SttConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    executors: list[ExecutorConfig] = Field(default_factory=_default_executors)
    stages: list[StageConfig] = Field(
        default_factory=lambda: [
            StageConfig(kind="whisper_detect"),
            StageConfig(kind="clock"),
            StageConfig(kind="system"),
        ]
    )
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    # записи владельца сливаются с умолчаниями по id (см. config/connectors.py)
    connectors: list[ConnectorConfig] = Field(default_factory=default_connectors)

    @field_validator("connectors", mode="before")
    @classmethod
    def _overlay_connectors(cls, value: object) -> object:
        return overlay_connectors(value)

    @model_validator(mode="after")
    def _check_single_entry(self) -> "Config":
        entries = [e for e in self.executors if e.entry]
        if len(entries) != 1:
            raise ValueError(f"нужен ровно один исполнитель с entry=true, найдено: {len(entries)}")
        return self

    @model_validator(mode="after")
    def _check_links(self) -> "Config":
        ids = [e.id for e in self.executors]
        for id_ in ids:
            if ids.count(id_) > 1:
                raise ValueError(f"id исполнителя повторяется: {id_}")
        for executor in self.executors:
            targets = [d.to for d in executor.delegates]
            for to in targets:
                if to == executor.id:
                    raise ValueError(f"исполнитель {executor.id} ссылается сам на себя")
                if to not in ids:
                    raise ValueError(f"исполнитель {executor.id} ссылается на несуществующего: {to}")
                if targets.count(to) > 1:
                    raise ValueError(f"исполнитель {executor.id} ссылается на {to} повторно")
        return self

    @model_validator(mode="after")
    def _check_connector_ids(self) -> "Config":
        ids = [c.id for c in self.connectors]
        for id_ in ids:
            if ids.count(id_) > 1:
                raise ValueError(f"id коннектора повторяется: {id_}")
        return self

    def entry_executor(self) -> ExecutorConfig:
        """Возвращает входного исполнителя (единственного с entry=True)."""
        return next(e for e in self.executors if e.entry)
