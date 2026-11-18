"""Фильтр журнала прячет токен из строки запроса."""

from __future__ import annotations

import logging

from smartesp.api import HideToken


def record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args or None, None)


def test_token_in_args_is_hidden_and_rest_kept() -> None:
    rec = record('%s - "GET %s HTTP/1.1" %d', "1.2.3.4:5", "/?token=a-b_c%25&x=1", 200)
    assert HideToken().filter(rec)
    assert rec.getMessage() == '1.2.3.4:5 - "GET /?token=***&x=1 HTTP/1.1" 200'


def test_token_in_message_and_quotes() -> None:
    rec = record("'WebSocket /api/v1/events?token=abc' [accepted]")
    HideToken().filter(rec)
    assert rec.getMessage() == "'WebSocket /api/v1/events?token=***' [accepted]"


def test_message_without_token_is_untouched() -> None:
    rec = record("percent %d", 5)
    HideToken().filter(rec)
    assert (rec.msg, rec.args) == ("percent %d", (5,))
