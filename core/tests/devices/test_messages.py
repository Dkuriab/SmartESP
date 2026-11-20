"""Тесты разбора и кодирования сообщений протокола колонок."""

import json

from smartesp.devices import (
    BargeIn,
    Busy,
    Hello,
    PlaybackDone,
    Played,
    UtteranceEnd,
    Wake,
    announce,
    cancel_turn,
    listen,
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


def test_parse_busy() -> None:
    assert parse_message('{"type":"busy","turn":2147483649}') == Busy(2147483649)
    assert parse_message('{"type":"busy"}') is None


def test_parse_played() -> None:
    assert parse_message('{"type":"played","turn":2147483649,"bytes":16000}') == Played(2147483649, 16000)
    assert parse_message('{"type":"played","turn":1,"bytes":4294967295}') == Played(1, 4294967295)
    assert parse_message('{"type":"played","turn":1,"bytes":0}') == Played(1, 0)


def test_parse_played_rejects_bad_bytes() -> None:
    assert parse_message('{"type":"played","turn":1}') is None
    assert parse_message('{"type":"played","bytes":10}') is None
    assert parse_message('{"type":"played","turn":1,"bytes":-1}') is None
    assert parse_message('{"type":"played","turn":1,"bytes":4294967296}') is None
    assert parse_message('{"type":"played","turn":1,"bytes":1.5}') is None
    assert parse_message('{"type":"played","turn":1,"bytes":true}') is None
    assert parse_message('{"type":"played","turn":1,"bytes":"10"}') is None


def test_encode_announce_and_listen() -> None:
    assert announce(2147483649) == '{"type":"announce","turn":2147483649}'
    assert listen(2147483650) == '{"type":"listen","turn":2147483650}'


def test_encode_cancel_turn() -> None:
    assert json.loads(cancel_turn(5)) == {"type": "cancel_turn", "turn": 5}


def test_encoders_are_compact_json() -> None:
    assert reply_start(1) == '{"type":"reply_start","turn":1}'
    assert reply_end(2) == '{"type":"reply_end","turn":2}'
    assert tone("ok") == '{"type":"tone","name":"ok"}'
    assert stop_playback() == '{"type":"stop_playback"}'


def test_non_finite_level_becomes_lowest() -> None:
    for raw in ("NaN", "Infinity", "-Infinity", "1e999", "9" * 400):
        message = parse_message('{"type":"wake","turn":1,"level":' + raw + "}")
        assert message == Wake(turn=1, level=-1000.0), raw


def test_parse_deep_nesting_does_not_raise() -> None:
    assert parse_message("[" * 100000) is None
    assert parse_message('{"type":"wake","turn":1,"x":' + "[" * 100000) is None
