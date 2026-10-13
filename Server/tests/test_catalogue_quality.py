import json
from types import SimpleNamespace

import pytest

from app.curated_recipes import CURATED_RECIPES
from app.food_filters import ingredient_has_allergen, recipe_is_compatible
from app.nutrition import REFERENCE, calculate_nutrition
from app.recipe_catalog import CATALOG_BY_NAME, RECIPE_CATALOG, RETIRED_RECIPE_NAMES
from tests.test_fridge_flow import fridge_client


def test_margherita_has_no_placeholder_meat_or_mushrooms():
    recipe = CATALOG_BY_NAME["Домашняя пицца Маргарита"]
    assert recipe["diet"] == "vegetarian"
    assert set(recipe["ingredients"]) == {"Мука пшеничная", "Дрожжи сухие", "Оливковое масло", "Томаты", "Сыр моцарелла", "Базилик"}


def test_corrected_breakfasts_have_different_compositions_and_attributed_nutrition():
    breakfasts = [r for r in CURATED_RECIPES if r["meal_slot"] == "breakfast"]
    assert len(breakfasts) == 20
    assert len({json.dumps(r["ingredients"], sort_keys=True) for r in breakfasts}) == 20
    for recipe in RECIPE_CATALOG:
        assert recipe["nutrition_status"] == "ingredient_estimate"
        assert recipe["calories"] > 0
        for product in recipe["ingredients"]:
            assert REFERENCE["foods"][product]["fdc_id"] > 0
            assert REFERENCE["foods"][product]["source_url"].startswith("https://fdc.nal.usda.gov/")
        assert len(recipe["instructions"].splitlines()) >= 3
        allergens = set(recipe["allergens"].split(","))
        for allergen in ("milk", "eggs", "gluten", "nuts", "fish", "soy", "sesame"):
            if any(ingredient_has_allergen(p, allergen) for p in recipe["ingredients"]):
                assert allergen in allergens


def test_nutrition_uses_weights_and_rejects_unknown_products():
    apple = REFERENCE["foods"]["Яблоко"]["per_100g"]
    result = calculate_nutrition({"Яблоко": 150})
    assert result["calories"] == round(apple["calories"] * 1.5, 2)
    assert result["protein"] == round(apple["protein"] * 1.5, 2)
    with pytest.raises(KeyError):
        calculate_nutrition({"Неизвестный продукт": 100})
    with pytest.raises(ValueError):
        calculate_nutrition({"Яблоко": -1})


def test_retired_database_rows_are_not_eligible_and_catalogue_has_unique_names():
    assert not set(CATALOG_BY_NAME) & RETIRED_RECIPE_NAMES
    assert len(CATALOG_BY_NAME) == len(RECIPE_CATALOG)
    for name in RETIRED_RECIPE_NAMES:
        assert not recipe_is_compatible(SimpleNamespace(name=name, diet="none", allergens="", ingredients='{"Рис":100}'), "none", set())


def test_existing_retired_row_is_hidden_from_api_without_deleting_it(fridge_client):
    from sqlalchemy.orm import Session
    from app.models import Recipe
    client, engine = fridge_client
    name = sorted(RETIRED_RECIPE_NAMES)[0]
    with Session(engine) as db:
        db.add(Recipe(name=name, calories=400, protein=20, fat=10, carbs=50,
                      ingredients='{"Рис":100}', diet="none", allergens="", meal_slot="main"))
        db.commit()
    recipes = client.get("/api/v1/recipes").json()["recipes"]
    assert name not in {r["name"] for r in recipes}
    corrected = next(r for r in recipes if r["name"] == "Гречневая каша с яблоком")
    assert corrected["nutrition_status"] == "ingredient_estimate"
    with Session(engine) as db:
        assert db.query(Recipe).filter_by(name=name).one() is not None
        from app.models import Profile
        db.query(Profile).filter_by(user_id=1).delete()
        db.commit()
    without_profile = client.get("/api/v1/recipes").json()["recipes"]
    assert name not in {r["name"] for r in without_profile}


def test_catalogue_identifies_preparation_state_instead_of_ambiguous_food_groups():
    ambiguous = {"Овощи", "Ягоды", "Растительное молоко", "Орехи", "Сыр", "Мука", "Нут", "Фасоль", "Творог"}
    for recipe in RECIPE_CATALOG:
        assert not set(recipe["ingredients"]) & ambiguous
        assert recipe["nutrition_status"] == "ingredient_estimate"
    for name in ("Карри с нутом", "Хумус с питой и овощами"):
        assert "Нут варёный" in CATALOG_BY_NAME[name]["ingredients"]
    for name in ("Овощное рагу с фасолью", "Буррито с фасолью"):
        assert "Фасоль варёная" in CATALOG_BY_NAME[name]["ingredients"]
    assert "cooked, boiled" in REFERENCE["foods"]["Нут варёный"]["description"]
    assert "raw" in REFERENCE["foods"]["Куриное филе"]["description"]


def test_seed_refreshes_nutrition_without_rewriting_saved_plan(fridge_client):
    from sqlalchemy.orm import Session
    from app.main import seed_recipes
    from app.models import Recipe, SavedPlan
    client, engine = fridge_client
    with Session(engine) as db:
        recipe = db.query(Recipe).filter_by(name="Гречка с курицей").one()
        original_id = recipe.id
        recipe.calories = 1
        old_plan = '{"meals": [{"recipe": "Гречка с курицей", "calories": 560}]}'
        db.add(SavedPlan(user_id=1, payload=old_plan))
        db.commit()
        seed_recipes(db)
        assert db.get(Recipe, original_id).calories == CATALOG_BY_NAME[recipe.name]["calories"]
        assert db.get(SavedPlan, 1).payload == old_plan
    response = client.get("/api/v1/recipes").json()["recipes"]
    assert all(r["nutrition_status"] == "ingredient_estimate" for r in response)


def test_small_scaled_ingredients_are_visible_and_agree_with_the_shopping_calculation(fridge_client):
    from sqlalchemy.orm import Session
    from app.main import _meal_payload
    from app.models import Recipe
    from app.recommender import PlannedMeal, shopping_list_for
    _, engine = fridge_client
    with Session(engine) as db:
        recipe = db.query(Recipe).filter_by(name="Домашняя пицца Маргарита").one()
        meal = PlannedMeal("обед", recipe, 0.75, 0, ())
        ingredients = {i["product"]: i["grams"] for i in _meal_payload(meal)["ingredients"]}
        assert ingredients["Дрожжи сухие"] == 1.5
        assert ingredients["Оливковое масло"] == 3.75
        assert _meal_payload(meal)["calories"] == round(recipe.calories * 0.75)
        shopping, _ = shopping_list_for([[meal]])
        yeast = next(i for i in shopping if i["product"] == "Дрожжи сухие")
        assert yeast["grams"] >= ingredients["Дрожжи сухие"]
