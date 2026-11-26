"""Поиск папки данных и загрузка config.yaml.

В config.yaml хранятся только настройки, которые владелец поменял сам; всё
остальное берётся из значений по умолчанию в коде, поэтому новые возможности
приходят без правки файла. Полный список значений по умолчанию — рядом, в
config.defaults.yaml (только для справки, перезаписывается при каждом старте).
"""

import os
import shutil
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ._files import owner_changes, read_yaml, write_overrides
from .models import BIG_DESCRIPTION, BIG_WHEN, CONFIG_VERSION, DEFAULT_SYSTEM_PROMPT, Config

DEFAULTS_HEADER = """# Значения по умолчанию — ТОЛЬКО ДЛЯ СПРАВКИ, ядро перезаписывает этот файл при старте.
# Чтобы поменять настройку, перенесите ключ в config.yaml.
"""
# Системные промпты по умолчанию прежних версий: в старом файле они значат «не меняли».
_OLD_PROMPT = (
    "Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
    "без разметки, списков и эмодзи — ответ будет озвучен."
)
_KUZYA_PROMPT = (
    "Тебя зовут Кузя. Ты голосовой помощник умной колонки. Отвечай по-русски, коротко, 1–3 предложения, "
    "без разметки, списков и эмодзи — ответ будет озвучен."
)
# умолчание волны 2: толкало на «нет доступа» и на вопросы общих знаний
_NO_ACCESS_PROMPT = (
    _KUZYA_PROMPT + " Ты знаешь только то, что есть в сообщении, в пометках и в ответах инструментов."
    " Не выдумывай время, погоду, новости и состояние устройств."
    " Нет данных или инструмента — скажи: «У меня нет доступа к …»."
    " Не говори, что что-то сделал, если инструмент этого не сделал."
)
# умолчание волны 3 (до правил по пунктам)
_WAVE3_PROMPT = (
    _KUZYA_PROMPT + " Время, погоду, новости и состояние устройств бери только из сообщения,"
    " пометок и ответов инструментов — не выдумывай их."
    " Не говори, что что-то сделал, если инструмент этого не сделал."
)
# умолчание с правилами по пунктам, до имени и рода из приложения (2026-11-22)
_RULES_PROMPT = (
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
# умолчание версии 6: общие знания — «отвечай сам», о поиске фактов ничего (до 2026-11-26)
_KNOWLEDGE_PROMPT = (
    "Твой ответ звучит голосом в доме. Правила:\n"
    "1. Отвечай по-русски и коротко: обычно одно предложение, не больше трёх. Без разметки, списков"
    " и эмодзи.\n"
    "2. Заметки, списки, таймеры, погода, расчёты, музыка, громкость колонок, поиск в интернете: если"
    " для этого есть инструмент — сначала вызови его, потом отвечай по его ответу. Про заметки и списки"
    " не отвечай по памяти: каждый раз смотри инструментом и называй, что там есть.\n"
    "3. Говори, что сделано («записано», «поставлено», «включено»), только если инструмент это сделал;"
    " ответил ошибкой — так и скажи. Просят что-то сделать (свет, техника, покупки), а инструмента для"
    " этого нет — скажи: «Этого я пока не умею». Никогда не говори, что это уже сделано.\n"
    "4. Время, погоду, числа, новости и состояние дома бери только из инструментов и справки."
    " Не знаешь — так и скажи, не выдумывай.\n"
    "5. В справке есть время, колонка, через которую с тобой говорят, что сейчас в работе и твои"
    " навыки. Говори о них, только когда об этом спросили.\n"
    "6. Не задавай вопросов в конце ответа и не предлагай помощь. Спрашивай, только если без уточнения"
    " просьбу не выполнить. Пример: «Привет, как дела?» — «Привет! Всё хорошо.»\n"
    "7. Разговор, шутки и общие знания — не действия: на них отвечай сам.\n"
    "8. Человек прощается или говорит, что больше ничего не нужно, — ответь одним словом: «Пока!»"
)
# условие и описание большой модели версии 6: «знания» уводили вопросы о фактах от поиска к ней
_KNOWLEDGE_WHEN = (
    "сложные вопросы: рассуждения, расчёты, подробные объяснения, знания, которых может не быть у тебя"
)
_KNOWLEDGE_DESCRIPTION = "большая модель: рассуждения, расчёты, подробные объяснения, знания"
# модель диспетчера по умолчанию прежних версий (до волны 3): в старом файле значит «не меняли»
_LEGACY_MODEL = "fredrezones55/Gemma-4-Uncensored-HauhauCS-Aggressive"
_LEGACY_PROMPTS = (
    DEFAULT_SYSTEM_PROMPT,
    _KNOWLEDGE_PROMPT,
    _RULES_PROMPT,
    _WAVE3_PROMPT,
    _NO_ACCESS_PROMPT,
    _KUZYA_PROMPT,
    _OLD_PROMPT,
    _OLD_PROMPT + " Если в сообщении есть пометка, что человек шепчет, начни ответ точно с [style:quiet]."
    " Во всех остальных случаях никаких меток не пиши.",
)


def data_dir() -> Path:
    """Папка данных: SMARTESP_HOME или ~/SmartEsp."""
    home = os.environ.get("SMARTESP_HOME")
    return Path(home) if home else Path.home() / "SmartEsp"


def load_config(path: Path) -> Config:
    """Читает настройки (см. load_with_overrides)."""
    return load_with_overrides(path)[0]


def load_with_overrides(path: Path) -> tuple[Config, dict[str, Any]]:
    """Читает настройки: изменения из config.yaml поверх значений по умолчанию.

    Нет файла — создаёт пустой (с подсказками). Файл прежнего формата (все
    настройки целиком, без version) один раз переводится: остаются только
    отличия от значений по умолчанию, старый файл сохраняется как config.yaml.bak.
    Файл версии 2–4 так же сохраняется в .bak и переписывается как версия 5 (tts без
    kind остаётся piper — прежнее умолчание; к сохранённым stages добавляются clock и system).
    Рядом пишется config.defaults.yaml. Файл не читается, не разбирается как YAML
    или настройки неверные — ValueError с понятным сообщением и путём к файлу.
    Возвращает настройки и изменения владельца (содержимое файла без version).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_defaults(path.with_name("config.defaults.yaml"))
    if not path.exists():
        write_overrides(path, {})
        return Config(), {}
    raw = read_yaml(path)
    version = raw.get("version")
    if version is not None and (isinstance(version, bool) or version not in (2, 3, 4, 5, 6, CONFIG_VERSION)):
        raise ValueError(f"файл настроек от более новой версии ядра: {path} (version: {version!r})")
    if version != CONFIG_VERSION:
        shutil.copyfile(path, path.with_name(path.name + ".bak"))
        if version is None:
            raw = _migrate(raw)
        if version in (None, 2):
            raw = _migrate_v2(raw)
        if version in (None, 2, 3):
            raw = _add_stage(raw, "clock")  # версии идут цепочкой: 2 → 3 → … → 7
        if version in (None, 2, 3, 4):
            raw = _add_stage(raw, "system")
        if version in (None, 2, 3, 4, 5):
            raw = _add_stage(raw, "people")
        raw = _refresh_knowledge(raw)
        write_overrides(path, raw)
    try:
        config = Config.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"неверные настройки в {path}:\n{error}") from error
    return config, {k: v for k, v in raw.items() if k != "version"}


def _add_stage(raw: dict[str, Any], kind: str) -> dict[str, Any]:
    """Переход версии: в сохранённый список stages добавляем новый обработчик kind (один раз).

    3 → 4 — clock, 4 → 5 — system, 5 → 6 — people. После перехода владелец, убравший обработчик, этот
    выбор сохраняет. Список, ставший равным умолчанию, из файла убирается.
    """
    raw = {k: v for k, v in raw.items() if k != "version"}
    stages = raw.get("stages")
    if isinstance(stages, list) and not any(isinstance(s, dict) and s.get("kind") == kind for s in stages):
        raw["stages"] = [*stages, {"kind": kind}]
        raw = owner_changes(raw, effective=False)
    return raw


def _refresh_knowledge(raw: dict[str, Any]) -> dict[str, Any]:
    """Версия 6 → 7: прежние тексты по умолчанию в сохранённых исполнителях → новые.

    Промпт, условие связи и описание, совпадающие с прежним умолчанием дословно, значат «не меняли»;
    свои тексты владельца остаются как есть. Список, ставший равным умолчанию, из файла убирается.
    """
    raw = {k: v for k, v in raw.items() if k != "version"}
    executors = raw.get("executors")
    if not isinstance(executors, list):
        return raw
    raw["executors"] = [_refresh_executor(item) for item in executors]
    return owner_changes(raw, effective=False)


def _refresh_executor(item: object) -> object:
    """Один сохранённый исполнитель с новыми текстами вместо прежних умолчаний."""
    if not isinstance(item, dict):
        return item
    item = dict(item)
    if item.get("system_prompt") == _KNOWLEDGE_PROMPT:
        item["system_prompt"] = DEFAULT_SYSTEM_PROMPT
    if item.get("description") == _KNOWLEDGE_DESCRIPTION:
        item["description"] = BIG_DESCRIPTION
    links = item.get("delegates")
    if isinstance(links, list):
        item["delegates"] = [_refresh_link(link) for link in links]
    return item


def _refresh_link(link: object) -> object:
    """Связь с прежним условием по умолчанию → с новым."""
    if isinstance(link, dict) and link.get("when") == _KNOWLEDGE_WHEN:
        return {**link, "when": BIG_WHEN}
    return link


def _migrate_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Версия 2 → 3: умолчанием tts был piper, поэтому tts без kind закрепляем как piper."""
    raw = {k: v for k, v in raw.items() if k != "version"}
    tts = raw.get("tts")
    if isinstance(tts, dict) and "kind" not in tts:
        raw["tts"] = {"kind": "piper", **tts}
    return raw


def _migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """Файл прежнего формата → только отличия от значений по умолчанию."""
    raw = dict(raw)
    if raw.get("stages") == []:
        del raw["stages"]  # прежнее умолчание «без обработчиков», а не выбор владельца
    if raw.get("tts") == {"kind": "piper", "voice": "ru_RU-irina-medium"}:
        del raw["tts"]  # прежнее умолчание-голос, а не выбор владельца
    if _is_legacy_executors(raw.get("executors")):
        del raw["executors"]
    return owner_changes(raw, effective=False)


def _is_legacy_executors(value: object) -> bool:
    """Список исполнителей совпадает с умолчанием прежних версий (с любым прежним промптом)."""
    # прежнее умолчание — один диспетчер без связей (сеть из двух исполнителей появилась позже),
    # на прежней модели и без поля reasoning
    legacy = Config().executors[0].model_dump(exclude={"delegates", "description", "reasoning", "gender"})
    legacy["model"] = _LEGACY_MODEL
    legacy["name"] = "Диспетчер"  # прежнее имя входного исполнителя (теперь он — сам ассистент)
    defaults = [legacy]
    if not isinstance(value, list) or len(value) != len(defaults):
        return False
    for item, default in zip(value, defaults, strict=True):
        if not isinstance(item, dict) or item.get("system_prompt") not in _LEGACY_PROMPTS:
            return False
        if {k: v for k, v in item.items() if k != "system_prompt"} != {
            k: v for k, v in default.items() if k != "system_prompt"
        }:
            return False
    return True


def _write_defaults(path: Path) -> None:
    """Пишет config.defaults.yaml — все значения по умолчанию, для справки."""
    body = yaml.safe_dump(Config().model_dump(), allow_unicode=True, sort_keys=False)
    path.write_text(DEFAULTS_HEADER + body, encoding="utf-8")
