import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base, get_db
from app.models import SavedPlan, User
from app.security import create_token


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id=1, email="one@example.com", password_hash="unused"), User(id=2, email="two@example.com", password_hash="unused")])
        db.flush()
        db.add(SavedPlan(user_id=1, payload=json.dumps({"period_days": 7, "shopping_list": [{"product": "Рис", "grams": 1200}]})))
        db.commit()
    def test_db():
        with Session(engine) as db:
            yield db
    previous = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_db] = test_db
    mock = AsyncMock(return_value={"available": False, "items": []})
    monkeypatch.setattr(main, "search_plan_products", mock)
    api = TestClient(main.app)
    try:
        yield api, mock
    finally:
        api.close()
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
        engine.dispose()


def auth(user_id):
    return {"Authorization": "Bearer " + create_token(user_id)}


def test_product_search_requires_authorization(client):
    api, mock = client
    assert api.post("/api/v1/stores/plan-products", json={}).status_code in (401, 403)
    mock.assert_not_awaited()


def test_product_search_uses_only_current_users_saved_plan(client):
    api, mock = client
    response = api.post("/api/v1/stores/plan-products", headers=auth(1), json={"region_id": 1})
    assert response.status_code == 200
    assert mock.await_args.args[0]["shopping_list"] == [{"product": "Рис", "grams": 1200}]
    mock.reset_mock()
    assert api.post("/api/v1/stores/plan-products", headers=auth(2), json={}).status_code == 400
    mock.assert_not_awaited()


def test_unknown_region_never_invokes_model(client):
    api, mock = client
    assert api.post("/api/v1/stores/plan-products", headers=auth(1), json={"region_id": 99}).status_code == 422
    mock.assert_not_awaited()


def test_unknown_week_is_reported_as_validation_error(client):
    api, mock = client
    mock.side_effect = ValueError("В рационе нет выбранной недели")
    response = api.post("/api/v1/stores/plan-products", headers=auth(1), json={"week_index": 2})
    assert response.status_code == 422
    assert "нет выбранной недели" in response.json()["detail"]


def test_unavailable_osm_does_not_hide_official_retail_prices(client, monkeypatch):
    import httpx
    api, _ = client
    shop = {"id": "verny:1", "chain": "Верный", "name": "Верный", "address": "Москва", "latitude": 55.75, "longitude": 37.62}
    item = {"id": "rice", "title": "РИС", "price": 129.99}
    catalogue = {"offers": [item], "stores": [shop], "status": "ok", "region": "Москва и обл.", "checked_at": "2026-10-08T00:00:00+00:00", "fetched_at": "2026-10-08T00:00:00+00:00"}
    monkeypatch.setattr(main, "load_catalogue", AsyncMock(return_value=catalogue))
    monkeypatch.setattr(main, "nearby_stores", AsyncMock(side_effect=httpx.ConnectTimeout("offline")))
    response = api.post("/api/v1/stores/compare", headers=auth(1), json={"latitude": 55.75, "longitude": 37.62, "product": "Рис"})
    assert response.status_code == 200
    assert response.json()["offers"] == [item]
    assert response.json()["stores"][0]["id"] == "verny:1"
    assert response.json()["location_status"] == "osm_unavailable"
