"""Заглушки audio_metadata и datasets для microWakeWord.

Они нужны только его классу Clips (чтение клипов через Hugging Face datasets), а мы подаём клипы
сами (clips.py). Ставить их нельзя без конфликтов (audio_metadata требует attrs<19.4), поэтому в
pyproject они убраны, а здесь — пустые модули, чтобы `import` в microwakeword прошёл.
"""

import sys
import types


def install() -> None:
    """Регистрирует пустые audio_metadata и datasets, если настоящих нет."""
    for name in ("audio_metadata", "datasets"):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
