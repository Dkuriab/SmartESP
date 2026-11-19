"""Короткие фразы для озвучки из ответа Open-Meteo."""

from datetime import date
from typing import Any

from weather_mcp.days import Day
from weather_mcp.speech import condition, degrees, meters_per_second, plain_number


def now_phrase(current: dict[str, Any]) -> str:
    """Погода сейчас: состояние, температура, ощущается, осадки, ветер."""
    parts = [
        f"Сейчас {condition(int(current['weather_code']))}, {degrees(current['temperature_2m'])}",
        f"ощущается как {degrees(current['apparent_temperature'])}",
    ]
    if current.get("precipitation", 0) > 0:
        parts.append(f"осадки {current['precipitation']:g} мм")
    wind = current["wind_speed_10m"]
    parts.append("ветра почти нет" if round(wind) == 0 else f"ветер {meters_per_second(wind)}")
    return ", ".join(parts) + "."


def _day_part(daily: dict[str, Any], index: int) -> str:
    low, high = daily["temperature_2m_min"][index], daily["temperature_2m_max"][index]
    parts = [condition(int(daily["weather_code"][index]))]
    if round(low) == round(high):
        parts.append(degrees(high))
    else:
        parts.append(f"от {plain_number(low)} до {degrees(high, True)}")
    rain = daily["precipitation_sum"][index] or 0
    chance = daily["precipitation_probability_max"][index]
    if rain > 0:
        parts.append(f"осадки {rain:g} мм")
    if chance is not None and chance > 0:
        parts.append(f"вероятность осадков {round(chance)} процентов")
    wind = daily["wind_speed_10m_max"][index]
    if wind is not None and round(wind) > 0:
        parts.append(f"ветер до {meters_per_second(wind, True)}")
    return ", ".join(parts)


def forecast_phrase(daily: dict[str, Any], today: date, day: Day) -> str | None:
    """Прогноз на день; None — если дня нет в данных."""
    dates = [date.fromisoformat(item) for item in daily["time"]]
    sentences: list[str] = []
    for offset in day.offsets:
        target = date.fromordinal(today.toordinal() + offset)
        if target not in dates:
            return None
        text = _day_part(daily, dates.index(target))
        if len(day.offsets) > 1:
            names = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
            text = f"{names[target.weekday()]}: {text}"
        sentences.append(text)
    head = day.label.capitalize()
    return f"{head}: " + "; ".join(sentences) + "."
