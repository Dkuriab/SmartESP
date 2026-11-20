"""Тесты сборки сообщений: справка (время, колонка) отдельно от пометок к реплике."""

from smartesp.contracts import Annotation, ChatMessage
from smartesp.conversation.prompt import CONTEXT_HEAD, REFERENCE_HEAD, build_messages

CLOCK = Annotation("четверг, 19 ноября 2026, 18:19", "clock", label="время", reference=True)
WHISPER = Annotation("человек говорит шёпотом", "whisper_detect")
HISTORY = [ChatMessage("user", "Привет"), ChatMessage("assistant", "Привет!")]


def test_reference_is_one_system_line_with_a_do_not_mention_rule() -> None:
    messages = build_messages([CLOCK], HISTORY, "Как дела?", "Кухня")
    assert messages == [
        *HISTORY,
        ChatMessage("system", f"{REFERENCE_HEAD} время — четверг, 19 ноября 2026, 18:19; колонка — Кухня."),
        ChatMessage("user", "Как дела?"),
    ]
    assert "Не упоминай" in REFERENCE_HEAD and "спросил" in REFERENCE_HEAD


def test_notes_stay_in_their_own_message_after_the_reference() -> None:
    messages = build_messages([WHISPER, CLOCK], [], "Тише", "Кухня")
    reference, notes, user = messages
    assert reference.content.startswith(REFERENCE_HEAD) and "шёпот" not in reference.content
    assert notes == ChatMessage("system", f"{CONTEXT_HEAD}\n[whisper_detect] человек говорит шёпотом")
    assert user == ChatMessage("user", "Тише")


def test_no_device_name_no_speaker_in_reference() -> None:
    (reference, _) = build_messages([CLOCK], [], "Который час?", "")
    assert reference.content == f"{REFERENCE_HEAD} время — четверг, 19 ноября 2026, 18:19."


def test_only_device_name() -> None:
    (reference, _) = build_messages([], [], "Привет", "Кухня")
    assert reference.content == f"{REFERENCE_HEAD} колонка — Кухня."


def test_nothing_to_add_only_history_and_question() -> None:
    assert build_messages([], HISTORY, "Привет", "") == [*HISTORY, ChatMessage("user", "Привет")]


def test_history_list_is_not_changed() -> None:
    history = list(HISTORY)
    build_messages([CLOCK, WHISPER], history, "Привет", "Кухня")
    assert history == HISTORY


def test_feed_only_annotation_does_not_reach_the_model() -> None:
    feed_only = Annotation("сказано шёпотом", "whisper_detect", to_model=False)
    assert build_messages([feed_only], [], "Привет", "") == [ChatMessage("user", "Привет")]
