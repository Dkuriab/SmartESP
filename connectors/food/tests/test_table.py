"""Тесты встроенной таблицы продуктов."""

from collections import Counter

from food_mcp.names import tokens
from food_mcp.table import table_foods

# Алкоголь даёт калории сверх Б/Ж/У — для него проверка суммы не годится.
ALCOHOL = {"пиво", "вино сухое", "водка"}


def test_size_and_keys_unique() -> None:
    foods = table_foods()
    assert len(foods) >= 140
    # Одно и то же название не должно вести к двум разным продуктам.
    keys = Counter(key for item in foods for key in {tokens(k) for k in item.keys})
    assert [key for key, count in keys.items() if count > 1] == []
    assert len({item.food.name for item in foods}) == len(foods)


def test_values_sane() -> None:
    for item in table_foods():
        food = item.food
        assert 0 <= food.kcal_100g <= 900, food
        assert all(0 <= v <= 100 for v in (food.protein, food.fat, food.carbs)), food
        assert food.protein + food.fat + food.carbs <= 100.5, food
        if food.name not in ALCOHOL:
            energy = 4 * food.protein + 9 * food.fat + 4 * food.carbs
            assert abs(energy - food.kcal_100g) <= max(25, 0.2 * food.kcal_100g), food


def test_known_entries() -> None:
    by_name = {item.food.name: item for item in table_foods()}
    assert by_name["гречка (сухая)"].food.kcal_100g == 343
    assert by_name["гречка варёная"].food.kcal_100g == 92
    assert by_name["яйцо куриное"].food.piece_grams == 55
    assert tokens("гречневая каша") in {tokens(k) for k in by_name["гречка варёная"].keys}
