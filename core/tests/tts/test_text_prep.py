"""Тесты подготовки текста и PCM для голосов."""

import numpy as np
import pytest
from num2words import num2words

from smartesp.tts.pcm import float_to_s16, scale_volume
from smartesp.tts.text_prep import keep_speakable, numbers_to_words


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("в 8 утра", "в восемь утра"),
        ("Сейчас 8:05.", "Сейчас восемь ноль пять."),
        ("Будет -3 градуса", "Будет минус три градуса"),
        ("Курс 2,5 или 2.5", "Курс две целых пять десятых или две целых пять десятых"),
        ("Заряд 50%", "Заряд пятьдесят процентов"),
        ("В 2024 году", "В две тысячи двадцать четыре году"),
        ("Без чисел.", "Без чисел."),
        ("Заряд 2,5%", "Заряд две целых пять десятых процентов"),
        ("Заряд 50 %", "Заряд пятьдесят процентов"),
    ],
)
def test_numbers_to_words(text: str, expected: str) -> None:
    assert numbers_to_words(text) == expected


def test_huge_number_is_spelled_by_digit() -> None:
    assert numbers_to_words(str(10**40)) == "один" + " ноль" * 40


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Привет — как дела?", "Привет - как дела?"),
        ("Подключи Wi-Fi, пожалуйста.", "Подключи , пожалуйста."),
        ("«Цитата» и… всё 😀", "Цитата и... всё"),
        ("№ 3 °C", "3"),
        ("1/2 стакана", "1 2 стакана"),
        ("кошки/собаки", "кошки собаки"),
        ("😀", ""),
    ],
)
def test_keep_speakable(text: str, expected: str) -> None:
    assert keep_speakable(text) == expected


def test_scale_volume_and_float_to_s16() -> None:
    pcm = float_to_s16(np.array([0.0, 0.5, -1.0, 2.0]))
    assert np.frombuffer(pcm, "<i2").tolist() == [0, 16383, -32767, 32767]
    quiet = np.frombuffer(scale_volume(pcm, 0.5), "<i2").tolist()
    assert quiet == [0, 8191, -16383, 16383]


def test_enormous_digit_run_does_not_raise() -> None:
    assert numbers_to_words("9" * 5000) == " ".join(["девять"] * 5000)


@pytest.mark.parametrize("sep", [" ", "\u00a0", "\u202f"])
@pytest.mark.parametrize(("grouped", "plain"), [("10{s}000", 10000), ("1{s}500", 1500)])
def test_thousand_separators(sep: str, grouped: str, plain: int) -> None:
    text = grouped.format(s=sep) + " шагов"
    assert numbers_to_words(text) == num2words(plain, lang="ru") + " шагов"


def test_small_negative_decimal_keeps_minus() -> None:
    assert numbers_to_words("-0,5").startswith("минус ")
