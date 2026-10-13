import asyncio
import json

import httpx
import pytest

from app import plan_preferences
from app.plan_preferences import PlanPreferences, PreferenceRequest, interpret_preferences
from tests.test_fridge_flow import fridge_client


def valid():
    return {"days": 7, "cooking_mode": "balanced", "desired_ingredients": ["рис"], "unhandled_requests": []}


@pytest.mark.parametrize("change", [{"days": 30}, {"cooking_mode": "weekly"}, {"calories": 300},
                                    {"restrictions": []}, {"desired_ingredients": ["x" * 81]}])
def test_model_cannot_override_profile_or_invent_periods(change):
    with pytest.raises(ValueError):
        PlanPreferences.model_validate_json(json.dumps({**valid(), **change}))


def test_unspecified_fields_can_remain_unchanged_and_blank_input_is_rejected():
    result = PlanPreferences.model_validate_json(json.dumps({**valid(), "days": None, "cooking_mode": None}))
    assert result.days is None and result.cooking_mode is None
    with pytest.raises(ValueError):
        PreferenceRequest(request="   ")


class FakeClient:
    output = valid()
    failure = False
    sent = None
    def __init__(self, **kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def post(self, url, json):
        type(self).sent = json
        if self.failure:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, request=httpx.Request("POST", url),
                              json={"message": {"content": __import__('json').dumps(self.output)}})


@pytest.fixture
def model(monkeypatch):
    FakeClient.output = valid()
    FakeClient.failure = False
    monkeypatch.setattr(plan_preferences.httpx, "AsyncClient", FakeClient)
    return FakeClient


def test_unavailable_model_does_not_invent_preferences(model):
    model.failure = True
    result = asyncio.run(interpret_preferences("На неделю", "http://local", "model"))
    assert not result["available"] and result["preferences"] is None


def test_invalid_output_does_not_change_form_fields(model):
    model.output = {**valid(), "days": 30}
    result = asyncio.run(interpret_preferences("На месяц", "http://local", "model"))
    assert not result["available"] and result["preferences"] is None


def test_model_default_period_is_not_applied_without_explicit_period(model):
    result = asyncio.run(interpret_preferences("Готовить с запасом", "http://local", "model"))
    assert result["available"] and result["preferences"]["days"] is None


def test_interpretation_does_not_create_plan_or_change_profile(fridge_client, model):
    from sqlalchemy.orm import Session
    from app.models import Profile, SavedPlan
    client, engine = fridge_client
    response = client.post("/api/v1/ai/plan-preferences", json={"request": "На неделю, через день, рис"})
    assert response.status_code == 200
    assert response.json()["preferences"] == valid()
    assert model.sent["format"]["additionalProperties"] is False
    with Session(engine) as db:
        assert db.get(SavedPlan, 1) is None
        assert db.get(Profile, 1).monthly_budget == 20000
