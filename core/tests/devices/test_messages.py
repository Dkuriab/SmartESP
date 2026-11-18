"""Тесты разбора и кодирования сообщений протокола колонок."""

import json

from smartesp.devices import (
    BargeIn,
    Hello,
    PlaybackDone,
    UtteranceEnd,
    Wake,
    cancel_turn,
    parse_message,
    reply_end,
    reply_start,
    stop_playback,
    tone,
)


def test_parse_wake_with_level() -> None:
    assert parse_message('{"type":"wake","turn":7,"level":-31.5}') == Wake(turn=7, level=-31.5)


def test_parse_wake_without_level() -> None:
    assert parse_message('{"type":"wake","turn":7}') == Wake(turn=7, level=None)


def test_parse_hello_v2() -> None:
    text = '{"type":"hello","fw":"2.0","device_id":"kitchen","protocol":2,"sample_rate":16000}'
    assert parse_message(text) == Hello(device_id="kitchen", fw="2.0", protocol=2)


def test_parse_hello_v1_without_device_id() -> None:
    assert parse_message('{"type":"hello","fw":"1.0"}') == Hello(device_id=None, fw="1.0", protocol=1)


def test_parse_other_messages() -> None:
    assert parse_message('{"type":"utterance_end","turn":3,"reason":"vad"}') == UtteranceEnd(3, "vad")
    assert parse_message('{"type":"barge_in","turn":4}') == BargeIn(4)
    assert parse_message('{"type":"playback_done","turn":2147483649}') == (PlaybackDone(2147483649))


def test_parse_garbage_returns_none() -> None:
    assert parse_message("не json") is None
    assert parse_message('{"type":"x"}') is None
    assert parse_message('{"type":"wake"}') is None
    assert parse_message("[1,2]") is None
    assert parse_message("null") is None


def test_parse_rejects_bad_turn_and_level() -> None:
    assert parse_message('{"type":"wake","turn":true}') is None
    assert parse_message('{"type":"wake","turn":-1}') is None
    assert parse_message('{"type":"wake","turn":1.5}') is None
    assert parse_message('{"type":"wake","turn":"1"}') is None
    assert parse_message('{"type":"wake","turn":1,"level":"loud"}') is None
    assert parse_message('{"type":"wake","turn":1,"level":true}') is None
    assert parse_message('{"type":"utterance_end","turn":1}') is None
    assert parse_message('{"type":"hello"}') is None


def test_encode_cancel_turn() -> None:
    assert json.loads(cancel_turn(5)) == {"type": "cancel_turn", "turn": 5}


def test_encoders_are_compact_json() -> None:
    assert reply_start(1) == '{"type":"reply_start","turn":1}'
    assert reply_end(2) == '{"type":"reply_end","turn":2}'
    assert tone("ok") == '{"type":"tone","name":"ok"}'
    assert stop_playback() == '{"type":"stop_playback"}'


def test_parse_rejects_non_finite_level() -> None:
    for raw in ("NaN", "Infinity", "-Infinity"):
        assert parse_message('{"type":"wake","turn":1,"level":' + raw + "}") is None


def test_parse_huge_level_does_not_raise() -> None:
    assert parse_message('{"type":"wake","turn":1,"level":' + "9" * 400 + "}") is None
    assert parse_message('{"type":"wake","turn":1,"level":1e999}') is None


def test_parse_deep_nesting_does_not_raise() -> None:
    assert parse_message("[" * 100000) is None
    assert parse_message('{"type":"wake","turn":1,"x":' + "[" * 100000) is None
