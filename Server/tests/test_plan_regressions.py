import json
from collections import Counter

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Profile, Recipe
from app.recipe_catalog import RECIPE_CATALOG
from app.recommender import PlannedMeal, make_plan, make_period_plan, shopping_list_for


@pytest.fixture
def catalogue():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for data in RECIPE_CATALOG:
            db.add(Recipe(**{key: data[key] for key in (
                "name", "calories", "protein", "fat", "carbs", "diet", "allergens",
                "preparation_minutes", "instructions", "meal_slot", "side_dish",
                "batch_servings", "storage_days")},
                ingredients=json.dumps(data["ingredients"]), estimated_cost=data["cost"]))
        db.commit()
        profile = Profile(user_id=1, sex="male", age=27, height_cm=179,
                          weight_kg=80, activity="low", goal="maintain", diet="none",
                          restrictions="", preferred_foods="", target_calories=2400,
                          monthly_budget=20000)
        yield db, profile
    engine.dispose()


@pytest.mark.parametrize("mode", ["variety", "balanced", "batch"])
def test_week_has_distinct_lunch_and_dinner(catalogue, mode):
    db, profile = catalogue
    _, days, _, _ = make_period_plan(db, profile, 7, cooking_mode=mode)
    previous = set()
    for index, day in enumerate(days):
        mains = [meal for meal in day if meal.recipe.meal_slot == "main"]
        names = {meal.recipe.name for meal in mains}
        assert len(names) == 2
        if mode == "variety":
            assert not names & previous
        for meal in mains:
            if meal.batch_servings_to_prepare == 0:
                assert meal.prepared_on_day < index
                source = next(m for m in days[meal.prepared_on_day] if m.meal == meal.meal)
                assert source.recipe.name == meal.recipe.name
                assert source.portion_multiplier == meal.portion_multiplier
        previous = names


@pytest.mark.parametrize("restrictions", ["milk", "eggs", "fish", "nuts", "soy", "sesame", "gluten"])
def test_week_filters_win_over_preferences_pantry_and_surprise(catalogue, restrictions):
    from app.food_filters import recipe_is_compatible
    from app.recommendation_rules import normalise_restrictions
    db, profile = catalogue
    profile.restrictions = restrictions
    _, days, _, _ = make_period_plan(
        db, profile, 7, pantry={"Сыр": 1000, "Орехи": 500, "Яйца": 600},
        desired_products={"сыр", "орехи", "яйца"}, surprise_me=True,
    )
    assert len(days) == 7
    for day in days:
        assert len(day) == 4
        assert all(recipe_is_compatible(m.recipe, "none", normalise_restrictions(restrictions)) for m in day)


def test_corrected_breakfasts_support_combined_restrictions(catalogue):
    db, profile = catalogue
    profile.restrictions = "milk,eggs,nuts"
    _, days, _, _ = make_period_plan(db, profile, 7, desired_products={"сыр"}, surprise_me=True)
    assert len(days) == 7
    from app.food_filters import recipe_is_compatible
    from app.recommendation_rules import normalise_restrictions
    assert all(recipe_is_compatible(m.recipe, "none", normalise_restrictions(profile.restrictions))
               for day in days for m in day)
    allowed = {r.name for r in db.query(Recipe).filter_by(meal_slot="breakfast")
               if recipe_is_compatible(r, "none", normalise_restrictions(profile.restrictions))}
    assert {"Гречневая каша с яблоком", "Каша булгур с фруктами"} <= allowed


@pytest.mark.parametrize("storage_days", [0, 1, 2])
def test_batch_does_not_plan_reheating_beyond_catalogue_storage_window(catalogue, storage_days):
    db, profile = catalogue
    for recipe in db.query(Recipe).filter_by(meal_slot="main"):
        recipe.storage_days = storage_days
        recipe.batch_servings = 3
    _, days, _, _ = make_period_plan(db, profile, 7, cooking_mode="batch")
    for index, day in enumerate(days):
        for meal in day:
            if meal.recipe.meal_slot != "main":
                continue
            assert meal.batch_servings_to_prepare <= max(1, storage_days)
            if meal.batch_servings_to_prepare == 0:
                assert index - meal.prepared_on_day < max(1, storage_days)


def test_scarce_catalogue_warns_without_admitting_allergen(catalogue):
    db, profile = catalogue
    mains = db.query(Recipe).filter_by(meal_slot="main").all()
    for recipe in mains:
        recipe.allergens = "nuts" if recipe != mains[0] else ""
    profile.restrictions = "nuts"
    _, days, _, _ = make_period_plan(db, profile, 3)
    assert all(m.recipe.name == mains[0].name for d in days for m in d if m.recipe.meal_slot == "main")
    assert any("Недостаточно совместимых блюд" in reason for d in days for m in d for reason in m.selection_reasons)


def test_prepared_dinner_is_reserved_and_usage_counts_actual_meals(catalogue):
    db, profile = catalogue
    recipe = db.query(Recipe).filter_by(meal_slot="main").first()
    prepared = PlannedMeal("Ужин", recipe, 1, 0, (), 0, 0)
    counts = Counter()
    _, day = make_plan(db, profile, counts, prepared_meals={"Ужин": prepared})
    assert next(m for m in day if m.meal == "Обед").recipe.name != recipe.name
    assert counts == Counter(m.recipe.name for m in day)


def test_pinned_dinner_remains_available_in_batch_mode(catalogue):
    db, profile = catalogue
    name = "Домашняя пицца Маргарита"
    _, days, _, _ = make_period_plan(db, profile, 3, cooking_mode="batch", pinned_recipe=name, pinned_meal="dinner")
    assert next(m for m in days[0] if m.meal == "Ужин").recipe.name == name
    assert next(m for m in days[0] if m.meal == "Обед").recipe.name != name


@pytest.mark.parametrize("grams, expected", [(1250, 3), (4, 1), (15000, 30)])
def test_package_size_stays_fixed_and_small_quantities_are_not_lost(grams, expected):
    recipe = Recipe(name="Рис", ingredients=json.dumps({"Рис": grams}))
    items, _ = shopping_list_for([[PlannedMeal("Обед", recipe, 1, 0, ())]])
    assert items[0]["grams"] == grams
    assert items[0]["package_grams"] == 500
    assert items[0]["packages_to_buy"] == expected
    assert items[0]["expected_leftover_grams"] == expected * 500 - grams


def test_pantry_aliases_are_added_and_stock_is_spent_once():
    recipe = Recipe(name="Рис", ingredients=json.dumps({"Рис": 100, "Риса": 100}))
    items, used = shopping_list_for([[PlannedMeal("Обед", recipe, 1, 0, ())]],
                                   {"рис": 60, "риса": 90})
    assert sum(i["grams"] for i in used) == 150
    assert sum(i["grams"] for i in items) == 50


def test_api_week_boundaries_saved_response_and_explicit_diet_reset():
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from app.db import get_db
    from app.main import app, current_user, seed_recipes
    from app.models import SavedPlan, User

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(User(id=1, email="test@example.com", password_hash="unused"))
        db.add(Profile(user_id=1, sex="male", age=27, height_cm=179, weight_kg=80,
                       activity="low", goal="maintain", diet="vegan", restrictions="nuts",
                       target_calories=2400, monthly_budget=20000))
        db.commit()
        seed_recipes(db)

    def get_test_db():
        with Session(engine) as db:
            yield db

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[current_user] = lambda: User(id=1)
    client = TestClient(app)
    try:
        response = client.post("/api/v1/plans/generate", json={"days": 1})
        assert response.status_code == 200, response.text
        assert response.json()["period_days"] == 1
        assert len(response.json()["days"]) == 1
        with Session(engine) as db:
            assert db.get(Profile, 1).diet == "vegan"
        response = client.post("/api/v1/plans/generate", json={"days": 7, "reset_diet": True})
        assert response.status_code == 200, response.text
        plan = response.json()
        assert plan["period_days"] == 7
        assert len(plan["days"]) == 7
        assert all(len(day["meals"]) == 4 for day in plan["days"])
        assert [(w["start_day"], w["end_day"]) for w in plan["weekly_shopping"]] == [(1, 7)]
        assert client.get("/api/v1/plans/current").json()["plan"] == plan
        assert not any(w.startswith("Недостаточно совместимых блюд") for w in plan["warnings"])
        assert not any("пока не пересчитаны" in w for w in plan["warnings"])
        for unsupported_days in (0, 2, 3, 6, 8, 30):
            response = client.post("/api/v1/plans/generate", json={"days": unsupported_days})
            assert response.status_code == 422, response.text
            assert client.get("/api/v1/plans/current").json()["plan"] == plan
        for request_options in ({"json": {}}, {}):
            response = client.post("/api/v1/plans/generate", **request_options)
            assert response.status_code == 200, response.text
            assert response.json()["period_days"] == 7
        with Session(engine) as db:
            assert db.get(Profile, 1).diet == "none"
            assert db.get(Profile, 1).restrictions == "nuts"
            # Changing generation periods must not delete previously saved long plans.
            legacy = dict(plan, period_days=30)
            saved = db.query(SavedPlan).filter_by(user_id=1).one()
            saved.payload = json.dumps(legacy)
            db.commit()
        assert client.get("/api/v1/plans/current").json()["plan"] == legacy
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)
        engine.dispose()
