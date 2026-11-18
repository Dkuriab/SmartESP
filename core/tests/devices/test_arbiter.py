"""Тесты арбитра: какая колонка услышала слово пробуждения лучше всех."""

from smartesp.devices import Arbiter, Decision

W, L = 0.3, 1.0


def acc(device: str, turn: int) -> Decision:
    return Decision("accept", device, turn)


def can(device: str, turn: int) -> Decision:
    return Decision("cancel", device, turn)


def make() -> Arbiter:
    return Arbiter(window_s=W, late_s=L)


def test_single_wake_accepted_after_window() -> None:
    a = make()
    assert a.on_wake("A", 1, -30.0, 0.0) == []
    assert a.poll(0.29) == []
    assert a.poll(0.31) == [acc("A", 1)]
    assert a.poll(0.5) == []


def test_louder_wins() -> None:
    a = make()
    a.on_wake("A", 1, -40.0, 0.0)
    a.on_wake("B", 2, -25.0, 0.1)
    assert a.poll(0.31) == [acc("B", 2), can("A", 1)]


def test_same_device_keeps_latest() -> None:
    a = make()
    a.on_wake("A", 1, -20.0, 0.0)
    a.on_wake("A", 2, -35.0, 0.1)
    assert a.poll(0.31) == [acc("A", 2)]


def test_late_wake_cancelled() -> None:
    a = make()
    a.on_wake("A", 1, -30.0, 0.0)
    a.poll(0.31)
    assert a.on_wake("C", 9, -20.0, 1.2) == [can("C", 9)]
    assert a.on_wake("C", 10, -20.0, 1.9) == []
    assert a.poll(2.3) == [acc("C", 10), can("A", 1)]


def test_late_wake_from_winner_opens_new_round() -> None:
    a = make()
    a.on_wake("A", 1, -30.0, 0.0)
    a.poll(0.31)
    assert a.on_wake("A", 2, -30.0, 0.5) == []
    assert a.poll(0.81) == [acc("A", 2)]


def test_new_wake_cancels_busy_other_device() -> None:
    a = make()
    a.on_wake("A", 1, -30.0, 0.0)
    a.poll(0.31)
    a.on_wake("B", 2, -30.0, 10.0)
    assert a.poll(10.31) == [acc("B", 2), can("A", 1)]


def test_finished_turn_not_cancelled() -> None:
    a = make()
    a.on_wake("A", 1, -30.0, 0.0)
    a.poll(0.31)
    a.on_turn_finished("A", 1)
    a.on_wake("B", 2, -30.0, 10.0)
    assert a.poll(10.31) == [acc("B", 2)]


def test_winner_own_earlier_turn_not_cancelled() -> None:
    a = make()
    a.on_wake("A", 1, -30.0, 0.0)
    a.poll(0.31)
    a.on_wake("A", 2, -30.0, 10.0)
    assert a.poll(10.31) == [acc("A", 2)]


def test_finish_unknown_turn_is_noop() -> None:
    a = make()
    a.on_turn_finished("Z", 5)
    a.on_wake("A", 1, -30.0, 0.0)
    a.poll(0.31)
    a.on_turn_finished("A", 99)
    a.on_wake("B", 2, -30.0, 10.0)
    assert a.poll(10.31) == [acc("B", 2), can("A", 1)]


def test_v1_device_accepted_immediately() -> None:
    a = make()
    assert a.on_wake("old", 1, None, 0.0) == [acc("old", 1)]
    assert a.poll(1.0) == []


def test_v1_device_neither_joins_nor_cancels() -> None:
    a = make()
    a.on_wake("A", 1, -30.0, 0.0)
    assert a.on_wake("old", 5, None, 0.1) == [acc("old", 5)]
    assert a.poll(0.31) == [acc("A", 1)]
    a.on_wake("B", 2, -30.0, 10.0)
    assert a.poll(10.31) == [acc("B", 2), can("A", 1)]
