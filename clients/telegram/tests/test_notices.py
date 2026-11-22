import io
import json

from telegram_bot.notices import StrangerNotices


def test_stranger_is_suggested_once_with_clean_name() -> None:
    out = io.StringIO()
    notices = StrangerNotices(out)
    notices(123, "Аня = ;Петрова")
    notices(123, "Аня")
    notices(456, "")
    lines = [json.loads(line)["suggest"] for line in out.getvalue().splitlines()]
    assert lines == [
        {
            "key": "TELEGRAM_USERS",
            "value": "123=Аня Петрова",
            "text": "Написал(а) боту: Аня Петрова (id 123)",
        },
        {"key": "TELEGRAM_USERS", "value": "456=без имени", "text": "Написал(а) боту: без имени (id 456)"},
    ]
