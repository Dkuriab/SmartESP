"""Подготовка текста для голосов: числа словами и чистка неозвучиваемого."""

import re

from num2words import num2words

_NUMBER = re.compile(
    r"(?P<time>\b(?P<hh>\d{1,2}):(?P<mm>\d{2})\b)"
    r"|(?:(?P<dec>(?<![\w-])-?\d+[.,]\d+)|(?P<int>(?<![\w-])-?\d+|\d+))(?P<pct>\s?%)?"
)
# Разделители тысяч: обычный, неразрывный и узкий неразрывный пробел.
_THOUSANDS = re.compile(r"(?<!\d)\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?!\d)")
_LATIN_WORD = re.compile(r"[A-Za-z][\w-]*")
_UNSPEAKABLE = re.compile(r"[^А-Яа-яЁё0-9\s.,!?:;\-()']")
_SPACES = re.compile(r"\s+")
_REPLACEMENTS = str.maketrans({"—": "-", "–": "-", "…": "..."})
_DROPPED = str.maketrans("", "", '«»"')


def _spell_digits(digits: str) -> str:
    """Читает число по одной цифре (запасной путь, если num2words не справился)."""
    return " ".join(num2words(int(d), lang="ru") for d in digits if d.isdigit())


def _words(raw: str) -> str:
    """Число (строкой) словами через num2words; при любой ошибке — по одной цифре."""
    sign = "минус " if raw.startswith("-") else ""
    raw = raw.lstrip("-")
    try:
        value = float(raw.replace(",", ".")) if re.search(r"[.,]", raw) else int(raw)
        return sign + num2words(value, lang="ru")
    except Exception:
        return sign + _spell_digits(raw)


def _time_to_words(hours: str, minutes: str) -> str:
    """«8:05» → «восемь ноль пять»: ведущий ноль минут читается как «ноль»."""
    minute_words = _words(minutes)
    if minutes.startswith("0") and int(minutes) != 0:
        minute_words = "ноль " + minute_words
    elif int(minutes) == 0:
        minute_words = "ноль ноль"
    return f"{_words(hours)} {minute_words}"


def _replace_number(match: re.Match[str]) -> str:
    """Заменяет одно найденное число его словесной записью."""
    if match.group("time"):
        return _time_to_words(match.group("hh"), match.group("mm"))
    result = _words(match.group("dec") or match.group("int"))
    return result + " процентов" if match.group("pct") else result


def numbers_to_words(text: str) -> str:
    """Заменяет числа в тексте словами: время, десятичные, целые, минус, проценты.

    Склонение не делается. Число, которое num2words не осилил, читается по цифрам.
    """
    text = _THOUSANDS.sub(lambda m: re.sub(r"\D", "", m.group()), text)
    return _NUMBER.sub(_replace_number, text)


def keep_speakable(text: str) -> str:
    """Оставляет только то, что озвучивается: кириллицу, цифры и простую пунктуацию.

    Слова с латиницей удаляются целиком, тире и многоточие приводятся к простому
    виду, кавычки и прочие символы убираются, пробелы схлопываются.
    """
    text = _LATIN_WORD.sub("", text).translate(_REPLACEMENTS).translate(_DROPPED)
    text = _UNSPEAKABLE.sub(" ", text)
    return _SPACES.sub(" ", text).strip()
