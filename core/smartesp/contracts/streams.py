"""Договор: поток звука на колонке — очередь источников (файл или ссылка), пауза, громкость.

Общий механизм, не музыка: ядро не знает ни папок, ни станций — их выбирает коннектор.
Колонка (протокол 5) сама тянет звук по одноразовой ссылке и сама приглушает его на время
разговора; ядро ведёт очередь и позицию по её отчётам stream_status.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

STREAM_RATE = 16000  # частота PCM потока (s16le, моно) по умолчанию: прошивка 0.6.0 умеет только её
HIFI_RATE = 48000  # прошивка 0.7.0 (hello stream_rates) играет и 48 кГц

# Состояние на колонке: ничего; играет (колонка может приглушить его на время разговора);
# на паузе (позиция запомнена).
StreamPhase = Literal["idle", "playing", "paused"]
StreamAction = Literal["pause", "resume", "next", "previous", "stop"]
# Почему не вышло: колонки нет; не в сети; протокол < 5; источник не годится; на колонке нет
# потока; не понятно, какая колонка; ядро останавливается.
StreamRefusal = Literal[
    "unknown_device", "offline", "unsupported", "bad_source", "not_playing", "no_device", "unavailable"
]
# Отчёт колонки: поток открыт (и раз в ~1 с, пока играет); кончился и доигран; остановлен
# командой; не открылся или оборвался.
StreamReportState = Literal["playing", "ended", "stopped", "failed"]


class StreamRefused(Exception):
    """Поток не начат или не изменён: reason — причина (для кода ответа), текст — для человека."""

    def __init__(self, reason: StreamRefusal, message: str) -> None:
        super().__init__(message)
        self.reason: StreamRefusal = reason


@dataclass(frozen=True)
class StreamItem:
    """Элемент очереди: source — абсолютный путь к звуковому файлу, ссылка http(s) (радио) или
    «capture:<часть имени устройства ввода>» — звук Mac (BlackHole); title — что показать и сказать
    человеку (пусто — имя файла, ссылка или «Звук Mac»)."""

    source: str
    title: str = ""


@dataclass(frozen=True)
class StreamInfo:
    """Поток на колонке для интерфейса и коннекторов.

    available — колонка в сети и умеет потоки; index — номер элемента очереди (с 0), count — длина
    очереди; position_s — позиция в элементе (у живого потока — сколько слушаем); live — ссылка
    (радио): перемотки нет, «продолжить» начинает заново; volume — громкость музыки 0..1
    относительно общей громкости колонки; error — последняя ошибка ("" — нет).
    """

    device_id: str
    name: str
    available: bool
    state: StreamPhase = "idle"
    title: str = ""
    index: int = 0
    count: int = 0
    position_s: float = 0.0
    live: bool = False
    volume: float = 0.6
    error: str = ""


@dataclass(frozen=True)
class StreamReport:
    """Отчёт колонки stream_status: номер потока, состояние, сколько байт PCM отдано динамику,
    ошибка ("", "download", "rate" или другое слово прошивки)."""

    stream: int
    state: StreamReportState
    played: int
    error: str = ""


@dataclass(frozen=True)
class StreamCommand:
    """Команда колонке: начать поток (path — ссылка на ядре), остановить, сменить громкость.

    stream — номер потока (0 в stop — любой); rate — частота PCM в ответе ссылки; live — живой
    поток (радио, звук Mac): на время разговора колонка глушит его, но продолжает читать — после
    разговора он идёт «сейчас», а не с места паузы.
    """

    kind: Literal["start", "stop", "volume"]
    stream: int = 0
    path: str = ""
    rate: int = STREAM_RATE
    volume: float = 1.0
    live: bool = False


# Отчёт колонки device_id; None — колонка отключилась (поток на ней больше не играет).
StreamListener = Callable[[str, StreamReport | None], None]


class StreamLink(Protocol):
    """Что потокам нужно от колонок; реализует DeviceHub."""

    def supports_stream(self, device_id: str) -> bool:
        """True, если колонка подключена и её протокол ≥ 5."""
        ...

    def stream_rate(self, device_id: str) -> int:
        """Частота PCM потока для колонки: наибольшая общая (hello stream_rates); нет поля — 16000."""
        ...

    async def send_stream(self, device_id: str, command: StreamCommand) -> bool:
        """Шлёт команду потока; False — колонка не подключена или протокол < 5."""
        ...

    def use_stream_listener(self, listener: StreamListener) -> None:
        """Куда отдавать отчёты колонок stream_status и их отключения."""
        ...


class SpeakerStreams(Protocol):
    """Потоки на колонках для API; реализует модуль streams.

    device_id None — колонку выбирает ядро: единственную с потоком, иначе колонку последнего
    разговора. Изменения — события stream {StreamInfo}.
    """

    def status(self) -> list[StreamInfo]:
        """Колонки, умеющие потоки, и колонки с потоком (в том числе на паузе), по имени."""
        ...

    async def play(
        self,
        device_id: str | None,
        items: Sequence[StreamItem],
        *,
        index: int = 0,
        start_s: float = 0.0,
        volume: float | None = None,
    ) -> StreamInfo:
        """Ставит очередь на колонку (прежний поток заменяется) и начинает элемент index с start_s.

        Отказ — StreamRefused (колонки нет, не в сети, протокол < 5, источник не годится).
        """
        ...

    async def control(self, device_id: str | None, action: StreamAction) -> StreamInfo:
        """Пауза, продолжить, дальше, назад, стоп. Нет потока — StreamRefused("not_playing")."""
        ...

    async def set_volume(
        self, device_id: str | None, *, volume: float | None = None, delta: float = 0.0
    ) -> StreamInfo:
        """Громкость музыки: volume (0..1) или сдвиг delta. Нет потока — StreamRefused."""
        ...

    async def open(self, token: str) -> AsyncIterator[bytes] | None:
        """Звук по одноразовой ссылке колонки: PCM s16le моно; None — ссылки нет или не разобрать."""
        ...
