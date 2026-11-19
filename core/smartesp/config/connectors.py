"""Коннекторы в настройках: умолчания и слияние записей владельца с ними по id.

Владелец в config.yaml пишет только то, что меняет, по id:
`connectors: [{id: weather, env: {WEATHER_PLACE: Москва}}]`. Поля записи заменяют поля
умолчания с тем же id, env сливается по ключам (null убирает ключ), запись с новым id
добавляет коннектор (нужны name и command), `remove: true` убирает коннектор. Умолчания,
о которых владелец не писал, остаются — новые коннекторы новых версий приходят сами.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

# корень репозитория: core/smartesp/config/connectors.py → вверх на четыре уровня
REPO_DIR = Path(__file__).resolve().parents[3]
REPO_PLACEHOLDER = "{repo}"  # в command, args и env коннектора заменяется на REPO_DIR при запуске
# наши коннекторы по умолчанию: (id, имя для людей, дополнительное окружение, включён ли);
# папка — connectors/<id>, команда — <id с «-» вместо «_»>-mcp
DEFAULT_CONNECTORS: tuple[tuple[str, str, dict[str, str], bool], ...] = (
    ("notes", "Заметки", {}, True),
    ("calc", "Калькулятор", {}, True),
    ("timers", "Таймеры", {}, True),
    ("weather", "Погода", {"WEATHER_PLACE": ""}, True),  # место впишет владелец; без него — «место не задано»
    ("food", "Питание", {}, True),
    ("mac_media", "Музыка и звук Mac", {}, True),
    # выключен, пока владелец не впишет разрешённые папки: «имя=путь;имя=путь»
    ("claude_tasks", "Задачи Клоду", {"CLAUDE_TASK_FOLDERS": ""}, False),
)
REMOVE = "remove"  # ключ записи владельца: убрать коннектор


class ConnectorConfig(BaseModel):
    """MCP-коннектор: команда запуска (stdio), окружение, включён ли.

    id — короткое имя из [A-Za-z0-9_-]: по нему папка данных коннектора. «{repo}» в
    command, args и значениях env — корень репозитория: настройки переживают его перенос.
    remove — только в записи владельца (убрать коннектор); в настройках его не бывает.
    """

    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    name: str
    command: str
    args: list[str] = Field(default_factory=list[str])
    env: dict[str, str] = Field(default_factory=dict[str, str])
    enabled: bool = True
    remove: bool = Field(default=False, exclude=True)

    def expanded(self) -> ConnectorConfig:
        """Копия, где «{repo}» заменён на путь к корню репозитория."""
        repo = str(REPO_DIR)
        return self.model_copy(
            update={
                "command": self.command.replace(REPO_PLACEHOLDER, repo),
                "args": [a.replace(REPO_PLACEHOLDER, repo) for a in self.args],
                "env": {k: v.replace(REPO_PLACEHOLDER, repo) for k, v in self.env.items()},
            }
        )


def default_connectors() -> list[ConnectorConfig]:
    """Наши коннекторы из папки connectors/ репозитория: `uv run --project <папка> <скрипт>`."""
    return [
        ConnectorConfig(
            id=cid,
            name=name,
            command="uv",
            args=["run", "--project", f"{REPO_PLACEHOLDER}/connectors/{cid}", f"{cid.replace('_', '-')}-mcp"],
            env=dict(env),
            enabled=enabled,
        )
        for cid, name, env, enabled in DEFAULT_CONNECTORS
    ]


def _defaults() -> list[dict[str, Any]]:
    return [c.model_dump(mode="json") for c in default_connectors()]


def _as_dict(item: object) -> object:
    """Запись как словарь (модель — через model_dump с remove); прочее — как есть."""
    if isinstance(item, ConnectorConfig):
        return {**item.model_dump(mode="json"), REMOVE: item.remove}
    return item


def _split(entries: list[Any]) -> tuple[dict[str, dict[str, Any]], list[object]]:
    """Записи с id (повтор id — ValueError) и записи без него (их отвергнет проверка настроек)."""
    by_id: dict[str, dict[str, Any]] = {}
    other: list[object] = []
    for raw in entries:
        item = _as_dict(raw)
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):  # pyright: ignore[reportUnknownMemberType]
            other.append(item)
            continue
        entry = cast(dict[str, Any], item)
        if entry["id"] in by_id:
            raise ValueError(f"id коннектора повторяется: {entry['id']}")
        by_id[entry["id"]] = dict(entry)
    return by_id, other


def _overlay_one(base: dict[str, Any], entry: dict[str, Any], keep_nulls: bool) -> dict[str, Any]:
    """Поля entry поверх base; env — по ключам. null поля — к умолчанию, null ключа env — убрать.

    keep_nulls — сохранить null в env (запись владельца поверх записи владельца).
    """
    result = copy.deepcopy(base)
    for key, value in entry.items():
        if key == "env" and isinstance(value, dict):
            env: dict[str, Any] = dict(result.get("env") or {})
            for name, text in value.items():  # pyright: ignore[reportUnknownVariableType]
                if text is None and not keep_nulls:
                    env.pop(str(name), None)  # pyright: ignore[reportUnknownArgumentType]
                else:
                    env[str(name)] = text  # pyright: ignore[reportUnknownArgumentType]
            result["env"] = env
        elif value is None:
            result.pop(key, None)
        else:
            result[key] = copy.deepcopy(value)
    return result


def overlay_connectors(entries: object) -> object:
    """Действующий список: умолчания с записями владельца по id, затем новые коннекторы владельца.

    Не список — как есть (ошибку типа даст проверка настроек).
    """
    if not isinstance(entries, list):
        return entries
    owner, other = _split(entries)  # pyright: ignore[reportUnknownArgumentType]
    result: list[object] = []
    for default in _defaults():
        entry = owner.pop(default["id"], None)
        if entry is None:
            result.append(default)
        elif not entry.get(REMOVE):
            result.append(_overlay_one(default, entry, keep_nulls=False))
    result += [_overlay_one({}, e, keep_nulls=False) for e in owner.values() if not e.get(REMOVE)]
    return result + other


def merge_connector_entries(base: list[Any], patch: list[Any]) -> list[object]:
    """Записи владельца с правкой: по id (поля заменяются, env — по ключам), новые id — в конец."""
    owner, other = _split(base)
    changes, more = _split(patch)
    for cid, entry in changes.items():
        owner[cid] = _overlay_one(owner.get(cid, {}), entry, keep_nulls=True)
    return [*owner.values(), *other, *more]


def _diff(entry: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
    """Поля entry, отличные от умолчания (env — по ключам; убранный ключ — null)."""
    diff = {k: v for k, v in entry.items() if k not in ("id", "env", REMOVE) and v != default.get(k)}
    env, base = entry.get("env") or {}, default.get("env") or {}
    changed = {k: v for k, v in env.items() if base.get(k) != v}
    changed.update({k: None for k in base if k not in env})
    if changed:
        diff["env"] = changed
    return diff


def connector_overrides(effective: object) -> list[object]:
    """Что писать в config.yaml: по каждому id только отличия от умолчания; убранное — remove.

    effective — действующий список целиком (записи владельца — сначала через overlay_connectors).
    """
    if not isinstance(effective, list):
        return [effective]
    defaults = {d["id"]: d for d in _defaults()}
    present: set[str] = set()
    result: list[object] = []
    for item in effective:
        cid = item.get("id") if isinstance(item, dict) else None
        if not isinstance(cid, str) or cid not in defaults:
            result.append({k: v for k, v in item.items() if k != REMOVE} if isinstance(item, dict) else item)
            continue
        present.add(cid)
        diff = _diff(item, defaults[cid])  # pyright: ignore[reportUnknownArgumentType]
        if diff:
            result.append({"id": cid, **diff})
    result += [{"id": cid, REMOVE: True} for cid in defaults if cid not in present]
    return result
