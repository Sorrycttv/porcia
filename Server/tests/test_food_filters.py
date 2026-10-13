import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-only-secret")

from app.food_filters import recipe_is_compatible
from app.main import _is_catalogue_compatible
from app.recommender import _is_compatible
from app.recommendation_rules import normalise_restrictions


@pytest.mark.parametrize("restriction, ingredient", [
    ("молоко", "Сыр"), ("milk", "Сливочное масло"),
    ("яйцо", "Яйца"), ("орехи", "Миндаль"),
    ("соя", "Соевый соус"), ("рыба", "Лосось"),
    ("кунжут", "Тахини"), ("глютен", "Макароны цельнозерновые"),
    ("курица", "Куриное филе"), ("курицы", "Куриное филе"),
    ("помидоры", "Томаты"), ("картошка", "Картофель"),
    ("рис", "Рис басмати"),
    ("глютен", "Мука"), ("глютен", "Овсяные хлопья"),
    ("глютен", "Пита"), ("глютен", "Ячменная крупа"),
    ("глютен", "Гранола"), ("соя", "Белок сои"),
    ("глютен", "Соевый соус"),
    ("глютен", "Безглютеновый хлеб с пшеничной мукой"),
])
def test_excluded_ingredient_is_rejected_in_plan_catalogue_and_fridge(restriction, ingredient):
    recipe = SimpleNamespace(diet="none", allergens="", ingredients=json.dumps({ingredient: 100}))
    restrictions = normalise_restrictions(restriction)
    assert not recipe_is_compatible(recipe, "none", restrictions)
    assert not _is_catalogue_compatible(recipe, "none", restrictions)
    assert not _is_compatible(recipe, SimpleNamespace(diet="none"), restrictions)


@pytest.mark.parametrize("restriction, ingredient", [
    ("молоко", "Кокосовое молоко"), ("глютен", "Пшено"),
    ("глютен", "Хлеб безглютеновый"), ("рис", "Редис"),
    ("глютен", "Рисовая мука"), ("глютен", "Кукурузная мука"),
    ("глютен", "Гречневая мука"),
    ("глютен", "Безглютеновая мука"),
    ("глютен", "Соевый соус безглютеновый"),
])
def test_unrelated_ingredients_are_not_rejected(restriction, ingredient):
    recipe = SimpleNamespace(diet="none", allergens="", ingredients=json.dumps({ingredient: 100}))
    assert recipe_is_compatible(recipe, "none", normalise_restrictions(restriction))


def test_declared_allergen_remains_authoritative():
    recipe = SimpleNamespace(diet="none", allergens="milk", ingredients='{"Кокосовое молоко": 100}')
    assert not recipe_is_compatible(recipe, "none", {"milk"})


def test_delimiters_case_and_russian_aliases():
    assert normalise_restrictions(" МОЛОКО; яйца\nорехи, milk ") == {"milk", "eggs", "nuts"}


@pytest.mark.parametrize("ingredients", ["broken", "null", "[]"])
def test_unknown_composition_not_accepted_with_restrictions(ingredients):
    recipe = SimpleNamespace(diet="none", allergens="", ingredients=ingredients)
    assert not recipe_is_compatible(recipe, "none", {"milk"})
