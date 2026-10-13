import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app import product_search
from app.product_search import apply_selections, candidates_for, week_items


def offer(id="rice", title="РИС"):
    return {"id": id, "title": title, "product": title + " 900 г", "price": 129.99,
            "package": "900 г", "package_quantity": 900, "package_unit": "g",
            "price_per_unit": 144.43, "conditions": "По карте"}


def rows():
    return candidates_for([{"product": "Рис", "grams": 1200}, {"product": "Гречка", "grams": 300}], [offer()], "")


def test_model_can_select_only_actual_card_without_changing_values():
    selected = apply_selections(rows(), json.dumps({"selections": [{"index": 0, "offer_id": "rice", "reason": "ingredient_match"}]}))
    assert selected[0]["offer"] == offer()
    assert selected[0]["grams"] == 1200
    assert selected[1]["offer"] is None


@pytest.mark.parametrize("selections", [
    [{"index": 0, "offer_id": "invented", "reason": "price"}],
    [{"index": 1, "offer_id": "rice", "reason": "price"}],
    [{"index": 0, "offer_id": "rice", "reason": "price", "price": 1}],
    [{"index": 9, "offer_id": None, "reason": "no_match"}],
    [{"index": 0, "offer_id": "rice", "reason": "no_match"}],
    [{"index": 0, "offer_id": "rice", "reason": "price"}] * 2,
])
def test_hallucinated_or_inconsistent_model_output_is_rejected(selections):
    with pytest.raises(ValueError):
        apply_selections(rows(), json.dumps({"selections": selections}))


def test_known_allergen_conflict_is_excluded_before_model_call():
    milk = offer("milk", "МОЛОКО")
    assert candidates_for([{"product": "Молоко", "grams": 100}], [milk], "milk")[0]["candidates"] == []


def test_condensed_milk_is_not_offered_for_plain_milk():
    assert candidates_for([{"product": "Молоко", "grams": 100}], [offer("milk", "МОЛОКО СГУЩЕННОЕ")], "")[0]["candidates"] == []


def test_second_week_uses_its_own_required_quantities():
    plan = {"weekly_shopping": [{"start_day": 1, "end_day": 7, "items": [{"product": "Рис", "grams": 100}]},
                                {"start_day": 8, "end_day": 14, "items": [{"product": "Рис", "grams": 220}]}]}
    assert week_items(plan, 1) == ([{"product": "Рис", "grams": 220}], 8, 14)
    with pytest.raises(ValueError):
        week_items(plan, 2)


def test_legacy_month_list_is_not_misrepresented_as_weekly():
    with pytest.raises(ValueError):
        week_items({"period_days": 30, "shopping_list": [{"product": "Рис", "grams": 1000}]}, 0)


def test_model_offline_returns_found_candidates_without_pretending_ai_selected(monkeypatch):
    catalogue = {"offers": [offer()], "region": "Москва и обл.", "status": "ok", "checked_at": "2026-10-08T00:00:00+00:00"}
    monkeypatch.setattr(product_search, "load_catalogue", AsyncMock(return_value=catalogue))
    class OfflineClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): raise httpx.ConnectTimeout("Offline")
    monkeypatch.setattr(product_search.httpx, "AsyncClient", lambda **kwargs: OfflineClient())
    result = asyncio.run(product_search.search_plan_products({"period_days": 7, "shopping_list": [{"product": "Рис", "grams": 100}]}, 0, 1, "", "http://ollama", "model"))
    assert result["available"] is False
    assert result["ai_status"] == "unavailable"
    assert result["items"][0]["offer"] is None
    assert result["items"][0]["candidates"] == [offer()]
