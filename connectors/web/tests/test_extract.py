"""Текст страницы: кодировка, заголовок, главное содержимое без меню и скриптов."""

from web_mcp.extract import decode, extract, plain_text

LONG = "Кот — домашнее животное, одно из наиболее популярных компаньонов человека. " * 5

PAGE = f"""<!doctype html><html><head>
<title>Кошка — Википедия</title>
<style>body {{ color: red }}</style>
<script>var secret = "скрипт";</script>
</head><body>
<header>Шапка сайта</header>
<nav><a href="/">Главная</a> <a href="/news">Новости</a></nav>
<article>
  <h1>Кошка</h1>
  <p>{LONG}</p>
  <p>Вторая   <b>часть</b>
     текста с <a href="/x">ссылкой</a>.</p>
  <ul><li>Первый пункт</li><li>Второй пункт</li></ul>
  <p>Строка<br>с переносом</p>
  <noscript>Включите JavaScript</noscript>
</article>
<aside>Реклама справа</aside>
<footer>Подвал © 2026</footer>
</body></html>"""


def test_extract_main_article_text() -> None:
    page = extract(PAGE)
    assert page.title == "Кошка — Википедия"
    lines = page.text.split("\n")
    assert lines[0] == "Кошка"
    assert lines[1].startswith("Кот — домашнее животное")
    assert "Вторая часть текста с ссылкой." in lines
    assert "Первый пункт" in lines and "Второй пункт" in lines
    assert "Строка" in lines and "с переносом" in lines
    for junk in ("скрипт", "color", "Шапка", "Главная", "Реклама", "Подвал", "JavaScript"):
        assert junk not in page.text


def test_og_title_wins_and_h1_is_fallback() -> None:
    og = '<html><head><meta property="og:title" content=" Новость дня "><title>Сайт | Новость</title></head>'
    assert extract(og + "<body><p>текст</p></body></html>").title == "Новость дня"
    assert extract("<html><body><h1>Только h1</h1><p>текст</p></body></html>").title == "Только h1"
    assert extract("<p>без заголовка</p>").title == ""


def test_short_main_falls_back_to_body() -> None:
    html = f"<html><body><main><p>Меню</p></main><div><p>{LONG}</p></div></body></html>"
    text = extract(html).text
    assert "Меню" in text
    assert "Кот — домашнее животное" in text


def test_longest_candidate_wins() -> None:
    html = (
        "<html><body><article><p>Короткая карточка</p></article>"
        f"<article><p>{LONG}</p></article></body></html>"
    )
    text = extract(html).text
    assert text.startswith("Кот — домашнее животное")
    assert "Короткая карточка" not in text


def test_empty_page_has_no_text() -> None:
    assert extract("<html><body><script>app()</script><div id='root'></div></body></html>").text == ""
    assert extract("").text == ""


def test_plain_text_normalised() -> None:
    assert plain_text("  первая   строка \r\n\n\n вторая\tстрока  ") == "первая строка\nвторая строка"


def test_decode_charset_from_header() -> None:
    body = "Привет".encode("cp1251")
    assert decode(body, "windows-1251") == "Привет"


def test_decode_charset_from_meta() -> None:
    body = '<html><head><meta charset="windows-1251"></head><body>Привет</body></html>'.encode("cp1251")
    assert "Привет" in decode(body, None)
    http_equiv = '<meta http-equiv="Content-Type" content="text/html; charset=windows-1251">Ёж'
    assert "Ёж" in decode(http_equiv.encode("cp1251"), None)


def test_decode_guesses_utf8_then_cp1251() -> None:
    assert decode("Привет".encode(), None) == "Привет"
    assert decode("Привет".encode("cp1251"), None) == "Привет"


def test_decode_unknown_charset_does_not_fail() -> None:
    assert decode("Привет".encode(), "x-unknown-charset") == "Привет"


def test_link_lists_and_hidden_blocks_are_dropped() -> None:
    languages = "".join(f'<li><a href="/{i}">Язык {i}</a></li>' for i in range(30))
    html = (
        f"<html><body><main><ul class='langs'>{languages}</ul>"
        "<div hidden><p>Скрытый блок</p></div>"
        "<div aria-hidden='true'><ul><li>Тоже скрыто</li></ul></div>"
        f"<p>{LONG}</p>"
        "<ul><li>Обычный пункт со <a href='/x'>ссылкой</a> внутри текста</li>"
        "<li>Второй пункт</li><li>Третий</li></ul></main></body></html>"
    )
    text = extract(html).text
    assert "Язык" not in text
    assert "крыт" not in text
    assert "Обычный пункт со ссылкой внутри текста" in text
    assert text.startswith("Кот — домашнее животное")
