import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app, current_user, seed_recipes
from app.models import FridgeItem, Profile, User
from app.recipe_catalog import RECIPE_CATALOG


@pytest.fixture
def fridge_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            User(id=1, email="inventory@example.com", password_hash="unused"),
            User(id=2, email="other@example.com", password_hash="unused"),
            Profile(user_id=1, sex="male", age=27, height_cm=179, weight_kg=80,
                    activity="low", goal="maintain", diet="none", restrictions="",
                    preferred_foods="", target_calories=2400, monthly_budget=20000),
            FridgeItem(user_id=2, product="Чужой запас", grams=123),
        ])
        db.commit()
        seed_recipes(db)

    def test_db():
        with Session(engine) as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[current_user] = lambda: User(id=1)
    client = TestClient(app)
    try:
        yield client, engine
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def test_fridge_keeps_fractional_grams_and_clears_only_its_owner(fridge_client):
    client, engine = fridge_client
    stock = [{"product": "Соль", "grams": 0.4}]
    assert client.put("/api/v1/fridge", json=stock).status_code == 200
    assert client.get("/api/v1/fridge").json()["items"] == stock
    assert client.put("/api/v1/fridge", json=[]).status_code == 200
    assert client.get("/api/v1/fridge").json()["items"] == []
    with Session(engine) as db:
        other = db.query(FridgeItem).filter_by(user_id=2).one()
        assert (other.product, other.grams) == ("Чужой запас", 123)


@pytest.mark.parametrize("days", [1, 7])
def test_saved_fridge_can_be_passed_to_plan_without_consuming_actual_stock(fridge_client, days):
    client, _ = fridge_client
    products = sorted({name for recipe in RECIPE_CATALOG for name in recipe["ingredients"]})
    stock = [{"product": name, "grams": 100000} for name in products]
    assert client.put("/api/v1/fridge", json=stock).status_code == 200
    saved_stock = client.get("/api/v1/fridge").json()["items"]
    assert all(item["product"] != "Чужой запас" for item in saved_stock)
    response = client.post("/api/v1/plans/generate", json={"days": days, "pantry": saved_stock})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["shopping_list"] == []
    assert plan["pantry_used"]
    assert all(week["items"] == [] for week in plan["weekly_shopping"])
    assert client.get("/api/v1/plans/current").json()["plan"] == plan
    assert client.get("/api/v1/fridge").json()["items"] == saved_stock
