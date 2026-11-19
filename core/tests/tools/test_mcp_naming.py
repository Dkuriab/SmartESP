"""Имена инструментов для модели: символы, длина, резерв, уникальность."""

from __future__ import annotations

from smartesp.tools.naming import MAX_NAME, pick_name, safe_name


def test_safe_name_replaces_bad_chars():
    assert safe_name("notes.add") == "notes_add"
    assert safe_name("заметка") == "_______"
    assert safe_name("") == "tool"
    assert safe_name("ok-name_1") == "ok-name_1"


def test_long_names_are_truncated_with_distinct_hash():
    a, b = safe_name("x" * 70 + "a"), safe_name("x" * 70 + "b")
    assert len(a) == len(b) == MAX_NAME
    assert a != b
    assert safe_name("x" * 70 + "a") == a  # детерминированно


def test_pick_name_order_and_reserve():
    assert pick_name(set(), "a", "echo") == "echo"
    assert pick_name({"echo"}, "b", "echo") == "b_echo"
    assert pick_name(set(), "a", "delegate") == "a_delegate"
    taken = {"echo", "b_echo"}
    hashed = pick_name(taken, "b", "echo")
    assert hashed is not None and hashed not in taken and hashed.startswith("b_echo_")
    assert pick_name(taken | {hashed}, "b", "echo") is None
