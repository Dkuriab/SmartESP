"""Настройки без наших коннекторов по умолчанию (они — настоящие `uv run`; в тестах не запускаем)."""

from __future__ import annotations

import json

from smartesp.config.connectors import DEFAULT_CONNECTORS

# записи владельца, убирающие все умолчания
NO_DEFAULT_CONNECTORS: list[dict[str, object]] = [
    {"id": cid, "remove": True} for cid, *_ in DEFAULT_CONNECTORS
]
# то же строкой YAML (JSON — это YAML)
NO_CONNECTORS_YAML = f"connectors: {json.dumps(NO_DEFAULT_CONNECTORS)}\n"
