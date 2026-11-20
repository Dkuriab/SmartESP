"""Разбор выдачи DuckDuckGo и фразы ответа поиска."""

from pathlib import Path

from web_mcp.search import SearchResult, looks_blocked, parse_results
from web_mcp.speech import domain, search_answer, shorten

FIXTURE = (Path(__file__).parent / "fixtures" / "ddg_results.html").read_text(encoding="utf-8")
CAPTCHA = (
    '<html><body><div class="anomaly-modal__title">Unfortunately, bots use DuckDuckGo too.</div>'
    '<form id="challenge-form" action="//duckduckgo.com/anomaly.js" method="POST"></form></body></html>'
)


def test_parse_top_five_skipping_ads_and_broken_links() -> None:
    results = parse_results(FIXTURE)
    assert [r.url for r in results] == [
        "https://cbr.ru/currency_base/daily/",
        "https://www.banki.ru/products/currency/usd/",
        "https://cbr.ru/hd_base/",
        "https://xn--80aswg.xn--p1ai/kurs",
        "https://yandex.ru/finance/currencies/usd_rub",
    ]


def test_parse_cleans_title_and_snippet() -> None:
    first = parse_results(FIXTURE)[0]
    assert first.title == "Официальные курсы валют на заданную дату"
    assert first.snippet == "Центральный банк установил с 20.11.2026 курс доллара США — 98,76 рубля."


def test_parse_result_without_snippet() -> None:
    assert parse_results(FIXTURE)[3].snippet == ""


def test_parse_empty_page() -> None:
    assert parse_results("<html><body><div id='links'></div></body></html>") == []
    assert parse_results("") == []


def test_blocked_detection() -> None:
    assert looks_blocked(202, CAPTCHA)
    assert looks_blocked(200, CAPTCHA)
    assert looks_blocked(403, "")
    assert looks_blocked(429, "")
    assert not looks_blocked(200, FIXTURE)


def test_domain_for_speech() -> None:
    assert domain("https://www.banki.ru/products/") == "banki.ru"
    assert domain("https://xn--80aswg.xn--p1ai/kurs") == "сайт.рф"
    assert domain("http://ru.wikipedia.org/wiki/x") == "ru.wikipedia.org"


def test_shorten_cuts_on_word_boundary() -> None:
    assert shorten("короткий текст", 50) == "короткий текст"
    cut = shorten("слово " * 30, 40)
    assert len(cut) <= 41
    assert cut.endswith("…")
    assert not cut[:-1].endswith(" ")


def test_search_answer_has_best_snippets_with_domains_and_links() -> None:
    text = search_answer("курс доллара", parse_results(FIXTURE))
    head, _, links = text.partition("Все результаты")
    # главное — три сниппета с доменами, сначала разные сайты, без адресов
    assert "cbr.ru: Центральный банк установил" in head
    assert "banki.ru: Покупка от 97,10" in head
    assert "yandex.ru: График и история" in head
    assert "Динамика официального курса" not in head
    assert "https://" not in head
    # список всех пяти — с адресами для web_read
    assert "https://cbr.ru/hd_base/" in links
    assert "сайт.рф" in links
    assert links.count("https://") == 5


def test_search_answer_falls_back_to_same_domain() -> None:
    results = [
        SearchResult("A", "https://a.ru/1", "Первый."),
        SearchResult("B", "https://a.ru/2", "Второй."),
        SearchResult("C", "https://a.ru/3", ""),
    ]
    head = search_answer("q", results).partition("Все результаты")[0]
    assert "a.ru: Первый." in head
    assert "a.ru: Второй." in head


def test_search_answer_without_snippets_names_titles() -> None:
    results = [SearchResult("Заголовок", "https://a.ru/1", "")]
    text = search_answer("q", results)
    assert "a.ru: Заголовок" in text
