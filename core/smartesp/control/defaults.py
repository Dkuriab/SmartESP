"""Значения по умолчанию для пульта: чего нет, пока main.py не подключил настоящее."""

from typing import Any

from smartesp.contracts import Answer, AskUnavailable, Question


async def no_models() -> list[dict[str, Any]]:
    """По умолчанию списка моделей (облако, LM Studio) нет."""
    return []


async def no_tools(model: str) -> bool:
    """По умолчанию модели считаются не умеющими инструменты."""
    return False


async def no_asking(question: Question) -> Answer:
    """По умолчанию ходов через API нет."""
    raise AskUnavailable("ходы через API не подключены")


async def no_decoding(audio: bytes) -> bytes:
    """По умолчанию звук не разбирается."""
    raise AskUnavailable("разбор звука не подключён")
