"""Тесты Open Food Facts: проверка штрихкода, разбор ответа, нет сети. Сеть — подделка."""

import os

import httpx
import pytest

from food_mcp.off import OpenFoodFacts, valid_barcode

from .conftest import BARCODE, BARCODE_8, FakeOff

NUTELLA = "3017620422003"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (BARCODE, BARCODE),
        ("4 607001 771562", BARCODE),
        ("4607001-771562", BARCODE),
        (BARCODE_8, BARCODE_8),
        ("036000291452", "036000291452"),
        ("4607001771563", None),
        ("12345", None),
        ("46070017715621", None),
        ("abc", None),
        ("", None),
    ],
)
def test_valid_barcode(raw: str, expected: str | None) -> None:
    assert valid_barcode(raw) == expected


def _product() -> dict[str, object]:
    return {
        "product_name": "Buckwheat",
        "product_name_ru": "Гречка ядрица",
        "brands": "Мистраль",
        "quantity": "900 г",
        "product_quantity": "900",
        "nutriments": {
            "energy-kcal_100g": 313,
            "proteins_100g": 12.6,
            "fat_100g": 3.3,
            "carbohydrates_100g": 57.1,
        },
    }


async def test_found_parses_product_and_sends_user_agent(off: FakeOff) -> None:
    off.products[BARCODE] = _product()
    result = await OpenFoodFacts(transport=off.transport()).lookup(BARCODE)
    assert result.status == "found"
    food = result.food
    assert food is not None
    assert food.name == "Гречка ядрица Мистраль"
    assert (food.kcal_100g, food.protein, food.fat, food.carbs) == (313, 12.6, 3.3, 57.1)
    assert food.pack_grams == 900
    assert food.barcode == BARCODE
    request = off.requests[0]
    assert request.url.host == "world.openfoodfacts.org"
    assert request.url.path == f"/api/v2/product/{BARCODE}"
    assert "nutriments" in request.url.params["fields"]
    assert request.headers["user-agent"] == "SmartEsp-food/0.1 (home assistant)"


async def test_name_fallbacks_and_kj(off: FakeOff) -> None:
    off.products[BARCODE] = {
        "product_name": "Choco Bar",
        "brands": "Choco, Other",
        "nutriments": {"energy_100g": 2092},
    }
    food = (await OpenFoodFacts(transport=off.transport()).lookup(BARCODE)).food
    assert food is not None
    assert food.name == "Choco Bar"
    assert food.kcal_100g == 500
    assert food.pack_grams == 0


async def test_missing(off: FakeOff) -> None:
    assert (await OpenFoodFacts(transport=off.transport()).lookup(BARCODE)).status == "missing"


async def test_status_zero_is_missing(off: FakeOff) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": 0})

    result = await OpenFoodFacts(transport=httpx.MockTransport(handler)).lookup(BARCODE)
    assert result.status == "missing"


async def test_no_kcal(off: FakeOff) -> None:
    off.products[BARCODE] = {"product_name": "Вода", "nutriments": {}}
    result = await OpenFoodFacts(transport=off.transport()).lookup(BARCODE)
    assert (result.status, result.name) == ("no_kcal", "Вода")


@pytest.mark.parametrize("mode", ["offline", "timeout"])
async def test_offline_and_timeout(off: FakeOff, mode: str) -> None:
    setattr(off, mode, True)
    assert (await OpenFoodFacts(transport=off.transport()).lookup(BARCODE)).status == "offline"


async def test_server_error_and_bad_json_are_offline() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>")

    for handler in (broken, garbage):
        result = await OpenFoodFacts(transport=httpx.MockTransport(handler)).lookup(BARCODE)
        assert result.status == "offline"


@pytest.mark.skipif(not os.environ.get("FOOD_LIVE_OFF"), reason="живой Open Food Facts: FOOD_LIVE_OFF=1")
async def test_live_open_food_facts() -> None:
    result = await OpenFoodFacts().lookup(NUTELLA)
    assert result.status == "found"
    assert result.food is not None
    assert 450 < result.food.kcal_100g < 600
