"""Именованные списки: файл `lists/<имя>.md`, пункт — строка `- `."""

from pathlib import Path

from .storage import normalize_text, read_text, safe_name, write_atomic

NO_NAME = "Не поняла, как назвать список."


def list_title(raw: str) -> str:
    """Нормализованное имя списка (пустое — имя не получилось)."""
    return safe_name(raw)


def _path(root: Path, title: str) -> Path:
    return root / "lists" / f"{title}.md"


def load(root: Path, title: str) -> list[str]:
    """Пункты списка по порядку."""
    lines = read_text(_path(root, title)).splitlines()
    return [line[2:] for line in lines if line.startswith("- ")]


def save(root: Path, title: str, items: list[str]) -> None:
    """Записывает список; пустой список — файл удаляется."""
    path = _path(root, title)
    if items:
        write_atomic(path, "".join(f"- {item}\n" for item in items))
    else:
        path.unlink(missing_ok=True)


def names(root: Path) -> list[str]:
    """Имена существующих списков по алфавиту."""
    folder = root / "lists"
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.md"))


def match(items: list[str], query: str) -> list[int]:
    """Индексы пунктов под запрос: точное совпадение побеждает частичное."""
    needle = normalize_text(query)
    if not needle:
        return []
    exact = [i for i, item in enumerate(items) if normalize_text(item) == needle]
    if exact:
        return exact[:1]
    return [i for i, item in enumerate(items) if needle in normalize_text(item)]


def clean_items(items: list[str]) -> list[str]:
    """Пункты без пустых и с одной строкой каждый."""
    return [" ".join(item.split()) for item in items if item.strip()]


def remove_items(current: list[str], queries: list[str]) -> tuple[set[int], list[str], list[str]]:
    """Разбирает запросы на вычёркивание.

    Возвращает: индексы к вычёркиванию, не найденные запросы, неоднозначные (с вариантами).
    """
    removed: set[int] = set()
    missing: list[str] = []
    unclear: list[str] = []
    for query in clean_items(queries):
        hits = match(current, query)
        if not hits:
            missing.append(query)
        elif len(hits) > 1:
            unclear.append(f"«{query}» — это {' или '.join(current[i] for i in hits)}")
        else:
            removed.add(hits[0])
    return removed, missing, unclear
