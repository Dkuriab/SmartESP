"""Тесты barcode-list.ru: разбор страницы, кэш, пауза, цепочка по штрихкоду. Сеть — подделка."""

import json
import os
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from food_mcp import barcode_list
from food_mcp.barcode_list import BarcodeList, NameResult, decode, parse_page
from food_mcp.barcode_match import candidates, pack_grams

from .conftest import NOW, Caller, Clock, FakeBarcodes, FakeOff, FakeTime, fixture_bytes

KEFIR = "4607025392408"
KEFIR_25 = "4607025392415"
UNKNOWN = "4600000000015"
HOME = "home"


def _page(name: str) -> str:
    return fixture_bytes(name).decode("utf-8")


def test_parse_prefers_title_when_same_name() -> None:
    assert parse_page(_page("kefir.html"), KEFIR) == NameResult("found", "ВМ Кефир 1% 0,950л")


def test_parse_uses_table_when_title_differs() -> None:
    page = _page("unknown.html").replace("<title>КОНФЕТЫ РОТ ФРОНТ 250Г", "<title>Другое")
    assert parse_page(page, UNKNOWN) == NameResult("found", "Конфеты рот фронт 250г")


def test_parse_unescapes_entities() -> None:
    assert parse_page(_page("entities.html"), "4600000000008").name == 'Йогурт "Чудо" & ягоды 125г'


def test_parse_row_with_other_code_is_unknown() -> None:
    assert parse_page(_page("kefir.html"), KEFIR_25).status == "unknown"


def test_parse_not_found_page_is_positive() -> None:
    assert parse_page(_page("empty.html"), "4600000000022") == NameResult("missing")
    assert parse_page("<html><body>Штрих-код не найден</body></html>", KEFIR) == NameResult("missing")


@pytest.mark.parametrize("fixture", ["captcha.html", "layout_changed.html"])
def test_parse_unexpected_page_is_unknown(fixture: str) -> None:
    assert parse_page(_page(fixture), KEFIR) == NameResult("unknown")


def test_parse_empty_table_without_form_is_unknown() -> None:
    page = _page("empty.html").replace(
        '<form action="/barcode/RU/Поиск.htm"><input name="barcode"></form>', ""
    )
    assert parse_page(page, "4600000000022").status == "unknown"


def test_parse_strips_control_chars_and_caps_length() -> None:
    page = _page("kefir.html").replace("ВМ КЕФИР 1% 0,950Л", "А\x07Б" + "я" * 300)
    name = parse_page(page, KEFIR).name
    assert "\x07" not in name
    assert len(name) <= 120


def test_decode_windows_1251_from_meta() -> None:
    raw = fixture_bytes("kefir_cp1251.html")
    assert "Кефир" in decode(raw, "text/html")


def test_decode_windows_1251_from_header() -> None:
    raw = "Кефир".encode("cp1251")
    assert decode(raw, "text/html; charset=windows-1251") == "Кефир"


def test_decode_guess_without_declaration() -> None:
    assert decode("Кефир".encode()) == "Кефир"
    assert decode("Кефир".encode("cp1251")) == "Кефир"


def test_decode_ignores_default_latin1_header() -> None:
    assert decode("Кефир".encode(), "text/html; charset=ISO-8859-1") == "Кефир"


def test_decode_bad_declared_charset_falls_back() -> None:
    assert decode("Кефир".encode(), "text/html; charset=nonsense") == "Кефир"


@pytest.mark.parametrize(
    ("name", "grams"),
    [
        ("ВМ Кефир 1% 0,950л", 950),
        ("Кофе Якобс 95гр", 95),
        ("Сыр 0.5 кг", 500),
        ("Виски (Classic, 0.5 л, Подарочн.)", 500),
        ("Йогурт 125Г", 125),
        ("Кефир Простоквашино", 0),
        ("Кефир 1% 3 литра", 0),
    ],
)
def test_pack_grams(name: str, grams: float) -> None:
    assert pack_grams(name) == grams


def test_candidates_prefer_more_specific_and_check_percent(data_dir: Path) -> None:
    assert [c.food.name for c in candidates(data_dir, "ВМ Кефир 1% 0,950л")] == ["кефир"]
    assert candidates(data_dir, "Кефир Простоквашино 2,5% 930мл") == []
    assert candidates(data_dir, "Болт BOSAL 258845") == []


async def test_lookup_found_sends_user_agent(barcodes: FakeBarcodes) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    result = await BarcodeList(barcodes.transport(), FakeTime()).lookup(KEFIR)
    assert (result.status, result.name) == ("found", "ВМ Кефир 1% 0,950л")
    request = barcodes.requests[0]
    assert request.headers["user-agent"] == "SmartEsp-food/0.1 (home assistant)"
    assert request.url.params["barcode"] == KEFIR
    assert request.url.host == "barcode-list.ru"


async def test_lookup_missing_offline_and_timeout(barcodes: FakeBarcodes) -> None:
    client = BarcodeList(barcodes.transport(), FakeTime())
    assert (await client.lookup(UNKNOWN)).status == "missing"
    barcodes.offline = True
    assert (await client.lookup(UNKNOWN)).status == "offline"

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("долго", request=request)

    assert (await BarcodeList(httpx.MockTransport(slow), FakeTime()).lookup(UNKNOWN)).status == "offline"


async def test_lookup_http_error_is_offline() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(503))
    assert (await BarcodeList(transport, FakeTime()).lookup(UNKNOWN)).status == "offline"


async def test_lookup_rate_limit_busy_when_wait_is_long(barcodes: FakeBarcodes) -> None:
    client = BarcodeList(barcodes.transport(), FakeTime(step=3))
    assert (await client.lookup(KEFIR)).status == "missing"
    assert (await client.lookup(KEFIR_25)).status == "busy"  # ждать 7 с > 6 с
    assert len(barcodes.requests) == 1


async def test_lookup_waits_for_short_slot(barcodes: FakeBarcodes) -> None:
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    client = BarcodeList(barcodes.transport(), FakeTime(step=6), sleep)
    await client.lookup(KEFIR)
    assert (await client.lookup(KEFIR_25)).status == "missing"
    assert slept == [pytest.approx(4)]
    assert len(barcodes.requests) == 2


async def test_failed_request_still_spends_slot(barcodes: FakeBarcodes) -> None:
    barcodes.offline = True
    client = BarcodeList(barcodes.transport(), FakeTime(step=3))
    assert (await client.lookup(KEFIR)).status == "offline"
    assert (await client.lookup(KEFIR)).status == "busy"


def test_cache_ttl_and_missing(data_dir: Path) -> None:
    found = barcode_list.NameResult("found", "Кефир")
    barcode_list.remember(data_dir, KEFIR, found, NOW)
    barcode_list.remember(data_dir, UNKNOWN, barcode_list.NameResult("missing"), NOW)
    barcode_list.remember(data_dir, KEFIR_25, barcode_list.NameResult("offline"), NOW)
    assert barcode_list.cached(data_dir, KEFIR, NOW + timedelta(days=29)) == found
    assert barcode_list.cached(data_dir, UNKNOWN, NOW + timedelta(days=1)) == barcode_list.NameResult(
        "missing"
    )
    assert barcode_list.cached(data_dir, KEFIR, NOW + timedelta(days=31)) is None
    assert barcode_list.cached(data_dir, KEFIR_25, NOW) is None


def test_cache_ignores_broken_file(data_dir: Path) -> None:
    (data_dir).mkdir(parents=True)
    (data_dir / barcode_list.CACHE_FILE).write_text("{oops")
    assert barcode_list.cached(data_dir, KEFIR, NOW) is None


async def test_default_does_not_ask_open_food_facts(
    call_default: Caller, off: FakeOff, barcodes: FakeBarcodes
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    await call_default("food_log", {"barcode": KEFIR})
    assert off.requests == []
    assert len(barcodes.requests) == 1


async def test_open_food_facts_opt_in_env(
    monkeypatch: pytest.MonkeyPatch, data_dir: Path, off: FakeOff, barcodes: FakeBarcodes, clock: Clock
) -> None:
    from food_mcp.server import build_server

    monkeypatch.setenv("FOOD_OFF", "1")
    server = build_server(
        data_dir, now=clock, transport=off.transport(), barcode_transport=barcodes.transport()
    )
    await Caller(server)("food_log", {"barcode": KEFIR})
    assert len(off.requests) == 1


async def test_suggests_table_food_and_never_logs(
    call_default: Caller, barcodes: FakeBarcodes, data_dir: Path
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    reply = await call_default("food_log", {"barcode": KEFIR})
    assert "ВМ Кефир 1% 0,950л" in reply
    assert "упаковка 950 г" in reply
    assert "«кефир» — 41 ккал на 100 г" in reply
    assert "Записать?" in reply
    assert not (data_dir / HOME / "diary").exists()


async def test_confirm_by_name_uses_pack_and_cached_name(
    call_default: Caller, barcodes: FakeBarcodes
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    await call_default("food_log", {"barcode": KEFIR})
    reply = await call_default("food_log", {"what": "кефир", "barcode": KEFIR})
    assert reply.startswith(
        "По штрихкоду нашла «ВМ Кефир 1% 0,950л». Записала: кефир, 1 упаковка, 950 г — 390 ккал."
    )
    assert len(barcodes.requests) == 1  # второй раз — из кэша


async def test_name_without_table_match_asks_kcal_then_product_add(
    call_default: Caller, barcodes: FakeBarcodes
) -> None:
    barcodes.pages[UNKNOWN] = fixture_bytes("unknown.html")
    reply = await call_default("food_log", {"barcode": UNKNOWN})
    assert "КОНФЕТЫ РОТ ФРОНТ 250Г, упаковка 250 г" in reply
    assert "сколько ккал на 100 г" in reply
    await call_default(
        "product_add", {"name": "Конфеты", "kcal_100g": 480, "barcode": UNKNOWN, "pack_grams": 250}
    )
    assert (await call_default("food_log", {"barcode": UNKNOWN, "grams": 20})).startswith(
        "Записала: Конфеты, 20 г"
    )


async def test_different_fat_percent_is_not_suggested(call_default: Caller, barcodes: FakeBarcodes) -> None:
    barcodes.pages[KEFIR_25] = fixture_bytes("kefir_25.html")
    reply = await call_default("food_log", {"barcode": KEFIR_25})
    assert "Похоже" not in reply
    assert "сколько ккал на 100 г" in reply


async def test_not_found_is_cached(call_default: Caller, barcodes: FakeBarcodes, clock: Clock) -> None:
    first = await call_default("food_log", {"barcode": UNKNOWN})
    assert first.startswith(f"Не знаю продукт со штрихкодом {UNKNOWN}")
    clock.now += timedelta(days=29)
    await call_default("food_log", {"barcode": UNKNOWN})
    assert len(barcodes.requests) == 1
    clock.now += timedelta(days=2)
    await call_default("food_log", {"barcode": UNKNOWN})
    assert len(barcodes.requests) == 2


async def test_offline_is_not_cached(call_default: Caller, barcodes: FakeBarcodes) -> None:
    barcodes.offline = True
    reply = await call_default("food_log", {"barcode": UNKNOWN})
    assert "Нет связи со справочником штрихкодов" in reply
    barcodes.offline = False
    assert (await call_default("food_log", {"barcode": UNKNOWN})).startswith("Не знаю продукт")


async def test_offline_falls_back_to_name(call_default: Caller, barcodes: FakeBarcodes) -> None:
    barcodes.offline = True
    reply = await call_default("food_log", {"what": "гречка (сухая)", "grams": 100, "barcode": KEFIR})
    assert reply.startswith(
        "Нет связи со справочником штрихкодов — считаю по названию. Записала: гречка (сухая)"
    )


async def test_busy_reply(data_dir: Path, barcodes: FakeBarcodes, clock: Clock) -> None:
    from food_mcp.server import build_server

    server = build_server(
        data_dir,
        now=clock,
        barcode_transport=barcodes.transport(),
        off_enabled=False,
        barcode_clock=FakeTime(step=1),
    )
    call = Caller(server)
    await call("food_log", {"barcode": KEFIR})
    assert "не чаще раза в 10 секунд" in await call("food_log", {"barcode": KEFIR_25})


async def test_own_barcode_skips_network(call_default: Caller, barcodes: FakeBarcodes) -> None:
    await call_default("product_add", {"name": "Мой кефир", "kcal_100g": 50, "barcode": KEFIR})
    assert (await call_default("food_log", {"barcode": KEFIR, "grams": 100})).startswith(
        "Записала: Мой кефир"
    )
    assert barcodes.requests == []


def test_cache_file_is_json(data_dir: Path) -> None:
    barcode_list.remember(data_dir, KEFIR, barcode_list.NameResult("found", "Кефир"), NOW)
    data = json.loads((data_dir / barcode_list.CACHE_FILE).read_text())
    assert data[KEFIR]["name"] == "Кефир"


@pytest.mark.skipif(os.environ.get("FOOD_LIVE_BARCODES") != "1", reason="нужна сеть: FOOD_LIVE_BARCODES=1")
async def test_live_barcode_list() -> None:
    result = await BarcodeList().lookup(KEFIR)
    assert result.status == "found"
    assert "кефир" in result.name.lower()


async def test_unexpected_page_is_not_cached_nor_found(
    call_default: Caller, barcodes: FakeBarcodes, data_dir: Path
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("captcha.html")
    reply = await call_default("food_log", {"barcode": KEFIR})
    assert "Не получилось найти" in reply
    assert "Just a moment" not in reply
    assert not (data_dir / barcode_list.CACHE_FILE).exists()
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    assert "Нашла: ВМ Кефир" in await call_default("food_log", {"barcode": KEFIR})


async def test_layout_changed_is_not_missing(
    call_default: Caller, barcodes: FakeBarcodes, data_dir: Path
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("layout_changed.html")
    assert "Не получилось найти" in await call_default("food_log", {"barcode": KEFIR})
    assert not (data_dir / barcode_list.CACHE_FILE).exists()


async def test_name_with_unknown_page_says_what_happened(
    call_default: Caller, barcodes: FakeBarcodes
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("captcha.html")
    reply = await call_default("food_log", {"what": "гречка (сухая)", "grams": 100, "barcode": KEFIR})
    assert reply.startswith("Справочник штрихкодов не ответил понятно — считаю по названию.")
    assert "калорийность не нашла" not in reply


async def test_busy_with_name_does_not_claim_not_found(
    data_dir: Path, barcodes: FakeBarcodes, clock: Clock
) -> None:
    from food_mcp.server import build_server

    call = Caller(
        build_server(
            data_dir,
            now=clock,
            barcode_transport=barcodes.transport(),
            off_enabled=False,
            barcode_clock=FakeTime(step=1),
        )
    )
    await call("food_log", {"barcode": KEFIR})
    reply = await call("food_log", {"what": "гречка (сухая)", "grams": 100, "barcode": KEFIR_25})
    assert reply.startswith("Справочник штрихкодов сейчас занят — считаю по названию.")
    assert "калорийность не нашла" not in reply


async def test_confirm_logs_offered_product_not_diary_preference(
    call_default: Caller, barcodes: FakeBarcodes
) -> None:
    # Раньше человек на «кефир» выбрал «кефир 3,2%»: дневник помнит это предпочтение.
    await call_default("product_add", {"name": "кефир 3,2%", "kcal_100g": 59})
    await call_default("food_log", {"what": "кефир", "grams": 100})
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    await call_default("food_log", {"barcode": KEFIR})
    reply = await call_default("food_log", {"what": "кефир", "barcode": KEFIR})
    assert "Записала: кефир, 1 упаковка, 950 г — 390 ккал." in reply


async def test_confirm_with_unoffered_name_is_ordinary_lookup(
    call_default: Caller, barcodes: FakeBarcodes
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    await call_default("food_log", {"barcode": KEFIR})
    reply = await call_default("food_log", {"what": "гречка (сухая)", "grams": 100, "barcode": KEFIR})
    assert "Записала: гречка (сухая)" in reply


async def test_offer_does_not_touch_pending_question(
    call_default: Caller, barcodes: FakeBarcodes, data_dir: Path
) -> None:
    await call_default("product_add", {"name": "гречка (варёная)", "kcal_100g": 110})
    assert "Уточни" in await call_default("food_log", {"what": "гречка", "grams": 100})
    pending = (data_dir / HOME / "pending.json").read_text()
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    assert "Нашла" in await call_default("food_log", {"barcode": KEFIR})
    assert (data_dir / HOME / "pending.json").read_text() == pending


async def test_barcode_cache_is_shared_between_people(
    call_default: Caller, barcodes: FakeBarcodes, data_dir: Path
) -> None:
    barcodes.pages[KEFIR] = fixture_bytes("kefir.html")
    await call_default("food_log", {"barcode": KEFIR}, person="Даня")
    reply = await call_default("food_log", {"barcode": KEFIR}, person="Маша")
    assert "Нашла: ВМ Кефир" in reply
    assert len(barcodes.requests) == 1
    assert (data_dir / barcode_list.CACHE_FILE).exists()
