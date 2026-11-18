"""Тесты истории диалога и сборки сообщений для исполнителя."""

from smartesp.contracts import Annotation, ChatMessage
from smartesp.conversation import History, build_messages


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_keeps_only_last_turns() -> None:
    history = History(max_turns=10, max_age_s=600)
    for i in range(11):
        history.add(f"вопрос {i}", f"ответ {i}")
    messages = history.messages()
    assert len(messages) == 20
    assert messages[0] == ChatMessage("user", "вопрос 1")
    assert messages[1] == ChatMessage("assistant", "ответ 1")
    assert messages[-1] == ChatMessage("assistant", "ответ 10")


def test_old_turns_expire() -> None:
    clock = FakeClock()
    history = History(max_turns=10, max_age_s=60, clock=clock)
    history.add("старый", "ответ")
    clock.now += 30
    history.add("новый", "ответ")
    clock.now += 31
    assert [m.content for m in history.messages()] == ["новый", "ответ"]


def test_build_messages() -> None:
    history = [ChatMessage("user", "раньше"), ChatMessage("assistant", "давно")]
    annotations = [Annotation(text="говорит Даня", source="voice"), Annotation(text="ночь", source="time")]
    messages = build_messages(annotations, history, "Который час?", "Кухня")
    assert messages[:2] == history
    assert messages[2] == ChatMessage(
        "user", "[voice] говорит Даня\n[time] ночь\nКолонка: Кухня\n\nКоторый час?"
    )


def test_build_messages_without_annotations() -> None:
    messages = build_messages([], [], "Привет", "Спальня")
    assert messages == [ChatMessage("user", "Колонка: Спальня\n\nПривет")]


def test_set_limits_keeps_newest() -> None:
    clock = FakeClock()
    history = History(max_turns=10, max_age_s=600, clock=clock)
    for i in range(5):
        history.add(f"вопрос {i}", f"ответ {i}")
    history.set_limits(max_turns=2, max_age_s=60)
    assert [m.content for m in history.messages()] == ["вопрос 3", "ответ 3", "вопрос 4", "ответ 4"]
    history.add("вопрос 5", "ответ 5")
    assert [m.content for m in history.messages() if m.role == "user"] == ["вопрос 4", "вопрос 5"]
    clock.now += 61
    assert history.messages() == []
