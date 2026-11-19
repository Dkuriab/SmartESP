"""Подсказки обработчиков добавляются к системному промпту входного исполнителя."""

from smartesp.config import Config, StageConfig
from smartesp.lifecycle import with_stage_hints
from smartesp.main import STAGE_KINDS


def test_enabled_stage_adds_its_hint_to_system_prompt() -> None:
    stage = STAGE_KINDS["whisper_detect"](StageConfig(kind="whisper_detect"))
    prompt = with_stage_hints("Базовый промпт.", [stage])
    assert prompt.startswith("Базовый промпт.")
    assert "[style:quiet]" in prompt


def test_no_stages_keeps_prompt() -> None:
    assert with_stage_hints("Базовый промпт.", []) == "Базовый промпт."


def test_default_prompt_does_not_mention_whisper() -> None:
    assert "шепчет" not in Config().entry_executor().system_prompt
