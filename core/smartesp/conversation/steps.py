"""Общие шаги хода — с колонки и через API: начало и конец, распознавание, понимание, история."""

import dataclasses
import logging
from collections.abc import Sequence

from smartesp.contracts import Analyzer, Annotation, ChatMessage, SpeechToText

from .activity import Publish, TurnActivity
from .history import History
from .prompt import build_messages
from .turn import Turn, answer_text, log_turn
from .turn_events import finished_data, heard_data, started_data
from .turn_messages import turn_messages

_log = logging.getLogger(__name__)


def begin(turn: Turn, publish: Publish) -> TurnActivity:
    """Начало хода: подсветка привязана к задаче хода (её узнают и вызовы инструментов), turn_started."""
    activity = TurnActivity.bind(turn, publish)
    publish("turn_started", started_data(turn))
    return activity


def end(turn: Turn, activity: TurnActivity, publish: Publish) -> None:
    """Конец хода: подсветка снята, turn_finished, итог в журнал."""
    activity.finish()
    publish("turn_finished", finished_data(turn))
    log_turn(turn)


async def hear(turn: Turn, stt: SpeechToText, publish: Publish) -> None:
    """Распознаёт звук реплики в turn.text, замеряет время, публикует turn_heard."""
    turn.text = await stt.transcribe(turn.utterance.pcm)
    turn.stt_ms = turn.elapsed_ms()
    publish("turn_heard", heard_data(turn))


async def understand(
    turn: Turn,
    analyze: Analyzer,
    history: History,
    device_name: str,
    context: Sequence[Annotation] = (),
) -> list[ChatMessage]:
    """Пометки обработчиков (в turn.annotations) и диалог для исполнителя.

    context — пометки только для промпта (в ленту не идут); device_name — имя колонки
    для справки (пусто — без него).
    """
    turn.annotations = await analyze(dataclasses.replace(turn.utterance, text=turn.text))
    return build_messages([*turn.annotations, *context], history.messages(), turn.text, device_name)


def settle(turn: Turn) -> None:
    """Итог ответа: пустой ответ модели у доведённого до конца хода — сбой."""
    if turn.completed and not answer_text(turn):
        _log.warning("%s: модель вернула пустой ответ", turn.device_name)
        turn.completed, turn.failed = False, True


def remember(turn: Turn, history: History) -> None:
    """Записывает в историю ход, доведённый до конца с непустым ответом."""
    if turn.completed and answer_text(turn):
        history.add_messages(turn_messages(turn))
