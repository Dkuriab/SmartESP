"""Параллельный запуск обработчиков со своими таймаутами."""

import asyncio
import logging

from smartesp.contracts import Annotation, Stage, Utterance

_log = logging.getLogger(__name__)


async def _run_one(stage: Stage, timeout: float, utterance: Utterance) -> list[Annotation]:
    """Запускает один обработчик; при таймауте или ошибке возвращает пустой список."""
    try:
        # wait_for отменяет задачу при таймауте и дожидается её завершения
        return await asyncio.wait_for(stage.analyze(utterance), timeout)
    except TimeoutError:
        _log.warning("Обработчик %s не уложился в %.2f с, пропущен", stage.name, timeout)
    except Exception:
        _log.warning("Обработчик %s упал, пропущен", stage.name, exc_info=True)
    return []


async def run_stages(stages: list[tuple[Stage, float]], utterance: Utterance) -> list[Annotation]:
    """Запускает все обработчики параллельно и собирает пометки.

    stages — пары (обработчик, таймаут в секундах). Упавшие и медленные
    пропускаются с предупреждением в логе. Порядок пометок — порядок списка.
    """
    results = await asyncio.gather(*(_run_one(s, t, utterance) for s, t in stages))
    return [a for part in results for a in part]
