"""Перевод кухонных единиц и деление поровну."""

import math
from dataclasses import dataclass

from calc_mcp.expr import format_number as _number

MAX_PARTS = 100000


class UnitError(ValueError):
    """Понятная ошибка перевода; текст пригоден для озвучки."""


@dataclass(frozen=True)
class Unit:
    """Единица: величина, коэффициент к базовой (г, мл), ключ и формы названия."""

    kind: str  # mass | volume | temp
    factor: float
    key: str
    forms: tuple[str, str, str, str]  # «1 стакан», «2 стакана», «5 стаканов», «2,5 стакана»


MASS = "mass"
VOLUME = "volume"
TEMP = "temp"

# Единицы и их написания (после нормализации: нижний регистр, без пробелов и точек).
UNIT_FORMS: tuple[tuple[Unit, tuple[str, ...]], ...] = (
    (
        Unit(MASS, 0.001, "мг", ("миллиграмм", "миллиграмма", "миллиграммов", "миллиграмма")),
        ("мг", "миллиграмм", "миллиграмма", "миллиграммов", "миллиграммы", "миллиграмы"),
    ),
    (
        Unit(MASS, 1, "г", ("грамм", "грамма", "граммов", "грамма")),
        ("г", "гр", "грамм", "грамма", "граммов", "граммы", "грамы"),
    ),
    (
        Unit(MASS, 1000, "кг", ("килограмм", "килограмма", "килограммов", "килограмма")),
        ("кг", "килограмм", "килограмма", "килограммов", "килограммы", "кило"),
    ),
    (
        Unit(MASS, 453.592, "фунт", ("фунт", "фунта", "фунтов", "фунта")),
        ("фунт", "фунта", "фунтов", "фунты", "lb", "lbs"),
    ),
    (
        Unit(MASS, 28.3495, "унция", ("унция", "унции", "унций", "унции")),
        ("унция", "унции", "унций", "унцию", "oz"),
    ),
    (
        Unit(VOLUME, 1, "мл", ("миллилитр", "миллилитра", "миллилитров", "миллилитра")),
        ("мл", "миллилитр", "миллилитра", "миллилитров", "миллилитры"),
    ),
    (
        Unit(VOLUME, 1000, "л", ("литр", "литра", "литров", "литра")),
        ("л", "литр", "литра", "литров", "литры"),
    ),
    (
        Unit(VOLUME, 5, "чл", ("чайная ложка", "чайные ложки", "чайных ложек", "чайной ложки")),
        ("чл", "чайнаяложка", "чайныеложки", "чайныхложек", "чайнойложки", "чайнуюложку"),
    ),
    (
        # Просто «ложка» в рецептах — столовая.
        Unit(VOLUME, 15, "стл", ("столовая ложка", "столовые ложки", "столовых ложек", "столовой ложки")),
        ("стл", "столоваяложка", "столовыеложки", "столовыхложек", "столовойложки", "столовуюложку")
        + ("ложка", "ложки", "ложек", "ложку"),
    ),
    (
        Unit(VOLUME, 250, "стакан", ("стакан", "стакана", "стаканов", "стакана")),
        ("стакан", "стакана", "стаканов", "стаканы"),
    ),
    (
        Unit(TEMP, 1, "°c", ("градус Цельсия", "градуса Цельсия", "градусов Цельсия", "градуса Цельсия")),
        ("°c", "c", "°с", "с", "цельсий", "цельсия", "градусцельсия", "градусовцельсия")
        + ("градусыцельсия", "градусацельсия"),
    ),
    (
        Unit(
            TEMP,
            1,
            "°f",
            ("градус Фаренгейта", "градуса Фаренгейта", "градусов Фаренгейта", "градуса Фаренгейта"),
        ),
        ("°f", "f", "фаренгейт", "фаренгейта", "градусфаренгейта", "градусовфаренгейта")
        + ("градусыфаренгейта", "градусафаренгейта"),
    ),
)

UNITS: dict[str, Unit] = {form: unit for unit, forms in UNIT_FORMS for form in forms}

# Плотность, г/мл.
DENSITY: dict[str, float] = {
    "мука": 0.53,
    "сахар": 0.85,
    "соль": 1.2,
    "рис": 0.85,
    "гречка": 0.8,
    "молоко": 1.03,
    "вода": 1.0,
    "масло растительное": 0.92,
    "масло сливочное": 0.91,
    "мёд": 1.4,
    "крупа манная": 0.8,
}

# Другие написания и родительный падеж («стакан муки»); ключи без «ё».
PRODUCT_ALIASES: dict[str, str] = {
    "муки": "мука",
    "сахара": "сахар",
    "сахарный песок": "сахар",
    "сахарного песка": "сахар",
    "соли": "соль",
    "риса": "рис",
    "гречки": "гречка",
    "гречневая крупа": "гречка",
    "гречневой крупы": "гречка",
    "молока": "молоко",
    "воды": "вода",
    "растительное масло": "масло растительное",
    "растительного масла": "масло растительное",
    "масла растительного": "масло растительное",
    "сливочное масло": "масло сливочное",
    "сливочного масла": "масло сливочное",
    "масла сливочного": "масло сливочное",
    "мед": "мёд",
    "меда": "мёд",
    "манная крупа": "крупа манная",
    "манной крупы": "крупа манная",
    "крупы манной": "крупа манная",
    "манка": "крупа манная",
    "манки": "крупа манная",
}

ABSOLUTE_ZERO_C = -273.15
ABSOLUTE_ZERO_F = -459.67


def _find_unit(name: str) -> Unit:
    key = "".join(ch for ch in name.lower() if not ch.isspace() and ch != ".")
    unit = UNITS.get(key)
    if unit is None:
        raise UnitError(f"Не знаю единицу «{name.strip()}».")
    return unit


def _find_density(product: str) -> tuple[str, float]:
    name = " ".join(product.lower().replace("ё", "е").split())
    exact = {key.replace("ё", "е"): key for key in DENSITY}
    name = exact.get(name) or PRODUCT_ALIASES.get(name, name)
    density = DENSITY.get(name)
    if density is None:
        known = ", ".join(DENSITY)
        raise UnitError(f"Не знаю плотность продукта «{product.strip()}», точно не переведу. Знаю: {known}.")
    return name, density


def _plural(unit: Unit, text: str) -> str:
    """Название единицы в нужном числе: «1 стакан», «2 стакана», «5 стаканов», «2,5 стакана»."""
    if "," in text:
        return unit.forms[3]
    number = abs(int(text))
    if 11 <= number % 100 <= 19:
        return unit.forms[2]
    if number % 10 == 1:
        return unit.forms[0]
    return unit.forms[1] if 2 <= number % 10 <= 4 else unit.forms[2]


def _say(value: float, unit: Unit) -> str:
    """Число с названием единицы."""
    text = _number(value)
    return f"{text} {_plural(unit, text)}"


def _temperature(value: float, src: Unit, dst: Unit) -> float:
    if src.key == dst.key:
        return value
    if src.key == "°c":
        if value < ABSOLUTE_ZERO_C:
            raise UnitError("Температура ниже абсолютного нуля.")
        return value * 9 / 5 + 32
    if value < ABSOLUTE_ZERO_F:
        raise UnitError("Температура ниже абсолютного нуля.")
    return (value - 32) * 5 / 9


def _scale(value: float, src: Unit, dst: Unit, product: str) -> tuple[float, str]:
    """Переводит массу/объём; между ними — через плотность продукта."""
    base = value * src.factor
    suffix = ""
    if src.kind != dst.kind:
        if not product.strip():
            raise UnitError("Для перевода между массой и объёмом нужен продукт, например мука или молоко.")
        name, density = _find_density(product)
        base = base * density if src.kind == VOLUME else base / density
        suffix = f" ({name})"
    return base / dst.factor, suffix


def _check_number(value: float, what: str) -> None:
    if not math.isfinite(value):
        raise UnitError(f"{what} должно быть обычным числом.")


def convert(value: float, from_unit: str, to_unit: str, product: str = "") -> str:
    """Переводит значение между единицами; ошибка — UnitError."""
    _check_number(value, "Значение")
    src, dst = _find_unit(from_unit), _find_unit(to_unit)
    if (src.kind == TEMP) != (dst.kind == TEMP):
        raise UnitError("Температуру можно переводить только в температуру.")
    if src.kind == TEMP:
        result, suffix = _temperature(value, src, dst), ""
    else:
        result, suffix = _scale(value, src, dst, product)
    if not math.isfinite(result):
        raise UnitError("Слишком большое число.")
    return f"{_say(value, src)} — это {_say(result, dst)}{suffix}"


def _split_say(value: float, unit_name: str) -> str:
    """Число с единицей; незнакомое слово («порций») повторяется как есть."""
    try:
        return _say(value, _find_unit(unit_name))
    except UnitError:
        tail = f" {unit_name.strip()}" if unit_name.strip() else ""
        return f"{_number(value)}{tail}"


def split(total: float, parts: int, unit: str = "") -> str:
    """Делит количество поровну на части; ошибка — UnitError."""
    _check_number(total, "Количество")
    if not 1 <= parts <= MAX_PARTS:
        raise UnitError("Число частей должно быть от 1 до 100000.")
    return f"{_split_say(total, unit)} на {parts} — по {_split_say(total / parts, unit)}"
