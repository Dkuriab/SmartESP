"""Короткие фразы для озвучки из ответа Open-Meteo. Пропуски в данных не роняют фразу."""

from datetime import date
from typing import Any

from weather_mcp.api import WeatherError
from weather_mcp.days import Day, weekday_label
from weather_mcp.speech import (
    condition,
    degrees,
    meters_per_second,
    millimeters,
    percent,
    plain_number,
    round_half_up,
)


def _value(source: dict[str, Any], key: str, index: int | None = None) -> float | None:
    """Число из ответа или None, если поля нет, оно null или не число."""
    try:
        item = source[key] if index is None else source[key][index]
    except (KeyError, IndexError, TypeError):
        return None
    if isinstance(item, bool) or not isinstance(item, int | float):
        return None
    return float(item)


def _condition(code: float | None) -> str | None:
    return None if code is None else condition(int(code))


def now_phrase(current: dict[str, Any]) -> str:
    """Погода сейчас: состояние, температура, ощущается, осадки, ветер."""
    temp = _value(current, "temperature_2m")
    if temp is None:
        raise WeatherError("no current temperature")
    head = "Сейчас"
    state = _condition(_value(current, "weather_code"))
    if state:
        head += f" {state},"
    parts = [f"{head} {degrees(temp)}"]
    feels = _value(current, "apparent_temperature")
    if feels is not None:
        parts.append(f"ощущается как {degrees(feels)}")
    rain = _value(current, "precipitation")
    if rain is not None and rain >= 0.1:
        parts.append(f"осадки {millimeters(rain)}")
    wind = _value(current, "wind_speed_10m")
    if wind is not None:
        parts.append("ветра почти нет" if round_half_up(wind) == 0 else f"ветер {meters_per_second(wind)}")
    return ", ".join(parts) + "."


def _day_part(daily: dict[str, Any], index: int) -> str:
    parts: list[str] = []
    state = _condition(_value(daily, "weather_code", index))
    if state:
        parts.append(state)
    low, high = _value(daily, "temperature_2m_min", index), _value(daily, "temperature_2m_max", index)
    if low is not None and high is not None:
        if round_half_up(low) == round_half_up(high):
            parts.append(degrees(high))
        else:
            parts.append(f"от {plain_number(low)} до {degrees(high, True)}")
    elif high is not None:
        parts.append(f"максимум {degrees(high)}")
    elif low is not None:
        parts.append(f"минимум {degrees(low)}")
    rain = _value(daily, "precipitation_sum", index)
    if rain is not None and rain >= 0.1:
        parts.append(f"осадки {millimeters(rain)}")
    chance = _value(daily, "precipitation_probability_max", index)
    if chance is not None and chance > 0:
        parts.append(f"вероятность осадков {percent(chance)}")
    wind = _value(daily, "wind_speed_10m_max", index)
    if wind is not None and round_half_up(wind) > 0:
        parts.append(f"ветер до {meters_per_second(wind, True)}")
    if not parts:
        raise WeatherError("empty day")
    return ", ".join(parts)


def forecast_phrase(daily: dict[str, Any], today: date, day: Day) -> str | None:
    """Прогноз на день; None — если дня нет в данных; кривые данные — WeatherError."""
    try:
        dates = [date.fromisoformat(item) for item in daily["time"]]
    except (KeyError, TypeError, ValueError) as error:
        raise WeatherError("bad daily dates") from error
    sentences: list[str] = []
    for offset in day.offsets:
        target = date.fromordinal(today.toordinal() + offset)
        if target not in dates:
            return None
        text = _day_part(daily, dates.index(target))
        if len(day.offsets) > 1:
            text = f"{weekday_label(target.weekday())} {text}"
        sentences.append(text)
    return f"{day.label.capitalize()}: " + "; ".join(sentences) + "."
