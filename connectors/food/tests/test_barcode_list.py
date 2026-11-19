"""Тесты barcode-list.ru: разбор страницы, кэш, пауза, цепочка по штрихкоду. Сеть — подделка."""

import json
import os
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from food_mcp import barcode_list
from food_mcp.barcode_list import BarcodeList, decode, parse_name
from food_mcp.barcode_match import candidates, pack_grams

from .conftest import NOW, Caller, Clock, FakeBarcodes, FakeOff, FakeTime, fixture_bytes

KEFIR = "4607025392408"
KEFIR_25 = "4607025392415"
UNKNOWN = "4600000000015"
HOME = "home"


def _page(name: str) -> str:
    return fixture_bytes(name).decode("utf-8")


def test_parse_prefers_title_when_same_name() -> None:
    assert parse_name(_page("kefir.html")) == "ВМ Кефир 1% 0,950л"


def test_parse_uses_table_when_title_differs() -> None:
    page = _page("unknown.html").replace("<title>КОНФЕТЫ РОТ ФРОНТ 250Г", "<title>Другое")
    assert parse_name(page) == "Конфеты рот фронт 250г"


def test_parse_falls_back_to_title_without_table() -> None:
    assert parse_name("<title>Кефир 1% - Штрих-код: 4607025392408</title>") == "Кефир 1%"


def test_parse_unescapes_entities() -> None:
    assert parse_name(_page("entities.html")) == 'Йогурт "Чудо" & ягоды 125г'


def test_parse_not_found_page() -> None:
    assert parse_name(_page("empty.html")) == ""
    assert parse_name("<html><title>Страница не найдена</title></html>") == ""


def test_decode_windows_1251_from_meta() -> None:
    raw = fixture_bytes("kefir_cp1251.html")
    assert "Кефир" in decode(raw, "text/html")


def test_decode_windows_1251_from_header() -> None:
    raw = "Кефир".encode("cp1251")
    assert decode(raw, "text/html; charset=windows-1251") == "Кефир"


def test_decode_guess_without_declaration() -> None:
    assert decode("Кефир".encode()) == "Кефир"
    assert decode("Кефир".encode("cp1251")) == "Кефир"


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


async def test_lookup_rate_limit_is_busy_without_request(barcodes: FakeBarcodes) -> None:
    client = BarcodeList(barcodes.transport(), FakeTime(step=3))
    assert (await client.lookup(KEFIR)).status == "missing"
    assert (await client.lookup(KEFIR_25)).status == "busy"
    assert len(barcodes.requests) == 1


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
