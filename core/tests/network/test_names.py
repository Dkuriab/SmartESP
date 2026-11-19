"""Тесты поиска имени цели во фразе без вызова инструмента."""

from smartesp.network import Target, named_target

BIG = Target("big", "Большая модель", "сложные вопросы")
CODER = Target("coder", "Программист", "код")
TARGETS = [BIG, CODER]


def test_phrase_with_inflected_two_word_name() -> None:
    assert named_target("Сейчас спрошу большую модель.", TARGETS) == BIG


def test_phrase_without_final_period() -> None:
    assert named_target("Спрошу программиста", TARGETS) == CODER


def test_case_and_spaces_ignored() -> None:
    assert named_target("  СЕЙЧАС СПРОШУ ПРОГРАММИСТА!  ", TARGETS) == CODER


def test_two_names_give_none() -> None:
    assert named_target("Спрошу программиста или большую модель.", TARGETS) is None


def test_no_name_gives_none() -> None:
    assert named_target("Сейчас подумаю.", TARGETS) is None


def test_only_part_of_name_gives_none() -> None:
    assert named_target("Сейчас спрошу модель.", TARGETS) is None


def test_long_answer_gives_none() -> None:
    text = "Сейчас спрошу большую модель, она точно знает, как это посчитать и объяснить подробно."
    assert len(text) > 80
    assert named_target(text, TARGETS) is None


def test_two_sentences_give_none() -> None:
    assert named_target("Хороший вопрос. Спрошу программиста.", TARGETS) is None


def test_empty_text_gives_none() -> None:
    assert named_target("", TARGETS) is None
    assert named_target("Спрошу программиста.", []) is None
