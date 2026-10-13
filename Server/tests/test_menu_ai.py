import json

import httpx
import pytest
from sqlalchemy.orm import Session

from app import menu_ai
from app.food_filters import recipe_is_compatible
from app.models import Profile, Recipe
from app.recommendation_rules import normalise_restrictions
from tests.test_fridge_flow import fridge_client


class FakeModel:
    sent = None
    failure = False
    mutate = None

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def post(self, url, json):
        if self.failure:
            raise httpx.ReadTimeout("offline")
        type(self).sent = json
        context = __import__('json').loads(json['messages'][-1]['content'])
        by_slot = {slot: [r['id'] for r in context['catalogue'] if r['slot'] == slot]
                   for slot in ('breakfast', 'main', 'snack')}
        choices = {'days': [dict(breakfast=by_slot['breakfast'][i % len(by_slot['breakfast'])],
                                lunch=by_slot['main'][(i * 2) % len(by_slot['main'])],
                                dinner=by_slot['main'][(i * 2 + 1) % len(by_slot['main'])],
                                snack=by_slot['snack'][i % len(by_slot['snack'])])
                            for i in range(context['days'])]}
        if type(self).mutate:
            type(self).mutate(choices)
        return httpx.Response(200, request=httpx.Request('POST', url),
            json={'message': {'content': __import__('json').dumps(choices)}})


@pytest.fixture
def model(monkeypatch):
    FakeModel.sent = None
    FakeModel.failure = False
    FakeModel.mutate = None
    monkeypatch.setattr(menu_ai.httpx, 'Client', FakeModel)
    return FakeModel


@pytest.mark.parametrize('days', [1, 7])
def test_ai_choices_are_applied_and_nutrition_shopping_and_saved_plan_are_server_results(fridge_client, model, days):
    client, engine = fridge_client
    with Session(engine) as db:
        db.get(Profile, 1).monthly_budget = None
        db.commit()
    response = client.post('/api/v1/plans/generate', json={'days': days, 'use_ai': True,
                                                         'menu_wish': 'с курицей'})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan['ai_selection']['status'] == 'applied'
    assert plan['ai_selection']['applied_meals'] == days * 4
    context = json.loads(model.sent['messages'][-1]['content'])
    assert 'email' not in context and 'weight_kg' not in context
    assert model.sent['format']['properties']['days']['minItems'] == days
    assert context['wish'] == 'с курицей'
    with Session(engine) as db:
        for day in plan['days']:
            for meal in day['meals']:
                recipe = db.query(Recipe).filter_by(name=meal['recipe']).one()
                # Public calorie output is rounded, but every other quantity
                # must agree with the server's recipe and portion multiplier.
                product, grams = next(iter(json.loads(recipe.ingredients).items()))
                actual_grams = next(i['grams'] for i in meal['ingredients'] if i['product'] == product)
                multiplier = actual_grams / grams
                assert abs(meal['calories'] - recipe.calories * multiplier) < 0.6
    assert plan['shopping_list']
    assert client.get('/api/v1/plans/current').json()['plan'] == plan


@pytest.mark.parametrize('bad_output', ['unknown', 'wrong_slot', 'extra_data', 'wrong_days', 'bool_id'])
def test_invalid_schedules_fall_back_without_accepting_any_model_choices(fridge_client, model, bad_output):
    client, _ = fridge_client
    baseline = client.post('/api/v1/plans/generate', json={'days': 7}).json()
    def mutate(output):
        day = output['days'][0]
        if bad_output == 'unknown': day['lunch'] = 999999
        if bad_output == 'wrong_slot': day['lunch'] = day['breakfast']
        if bad_output == 'extra_data': output['calories'] = 1
        if bad_output == 'wrong_days': output['days'].pop()
        if bad_output == 'bool_id': day['breakfast'] = True
    model.mutate = mutate
    plan = client.post('/api/v1/plans/generate', json={'days': 7, 'use_ai': True}).json()
    assert plan['ai_selection']['status'] == 'invalid_response'
    assert plan['ai_selection']['applied_meals'] == 0
    assert plan['days'] == baseline['days']
    assert plan['shopping_list'] == baseline['shopping_list']


@pytest.mark.parametrize('within_day', [False, True])
def test_repeated_model_suggestions_are_filtered_during_final_selection(fridge_client, model, within_day):
    client, engine = fridge_client
    with Session(engine) as db:
        db.get(Profile, 1).monthly_budget = None
        db.commit()
    def repeat_mains(output):
        if within_day:
            for day in output['days']:
                day['dinner'] = day['lunch']
        else:
            for day in output['days'][1:]:
                day.update(lunch=output['days'][0]['lunch'], dinner=output['days'][0]['dinner'])
    model.mutate = repeat_mains
    plan = client.post('/api/v1/plans/generate', json={'days': 7, 'use_ai': True}).json()
    assert plan['ai_selection']['status'] == 'applied'
    assert 0 < plan['ai_selection']['applied_meals'] < 28
    previous = set()
    for day in plan['days']:
        mains = {meal['recipe'] for meal in day['meals'] if meal['meal'] in ('Обед', 'Ужин')}
        assert len(mains) == 2
        assert not mains & previous
        previous = mains


def test_unavailable_ai_falls_back_and_disabled_requests_never_call_it(fridge_client, model):
    client, _ = fridge_client
    disabled = client.post('/api/v1/plans/generate', json={'days': 1}).json()
    assert disabled['ai_selection']['status'] == 'disabled' and model.sent is None
    model.failure = True
    result = client.post('/api/v1/plans/generate', json={'days': 1, 'use_ai': True}).json()
    assert result['ai_selection']['status'] == 'unavailable'
    assert result['days'] == disabled['days']


def test_allergens_are_removed_before_inference_and_forbidden_id_is_rejected(fridge_client, model):
    client, engine = fridge_client
    with Session(engine) as db:
        profile = db.get(Profile, 1)
        profile.restrictions = 'milk,eggs,nuts'
        forbidden = db.query(Recipe).filter_by(name='Омлет с овощами').one().id
        db.commit()
    model.mutate = lambda output: output['days'][0].update(breakfast=forbidden)
    plan = client.post('/api/v1/plans/generate', json={'days': 1, 'use_ai': True}).json()
    assert plan['ai_selection']['status'] == 'invalid_response'
    sent_ids = {r['id'] for r in json.loads(model.sent['messages'][-1]['content'])['catalogue']}
    assert forbidden not in sent_ids
    with Session(engine) as db:
        for recipe in db.query(Recipe).filter(Recipe.id.in_(sent_ids)):
            assert recipe_is_compatible(recipe, 'none', normalise_restrictions('milk,eggs,nuts'))


@pytest.mark.parametrize('mode', ['balanced', 'batch'])
def test_ai_cannot_replace_pinned_dish_or_reuse_or_expire_prepared_meals(fridge_client, model, mode):
    client, engine = fridge_client
    with Session(engine) as db:
        db.get(Profile, 1).monthly_budget = None
        db.commit()
    plan = client.post('/api/v1/plans/generate', json={
        'days': 7, 'use_ai': True, 'cooking_mode': mode,
        'pinned_recipe': 'Гречка с курицей', 'pinned_meal': 'lunch'}).json()
    assert plan['days'][0]['meals'][1]['recipe'] == 'Гречка с курицей'
    reused = 0
    for index, day in enumerate(plan['days']):
        mains = [meal for meal in day['meals'] if meal['meal'] in ('Обед', 'Ужин')]
        assert len({m['recipe'] for m in mains}) == 2
        for meal in day['meals']:
            if meal['batch_servings_to_prepare'] == 0:
                reused += 1
                source_index = meal['prepared_on_day']
                source = next(m for m in plan['days'][source_index]['meals'] if m['meal'] == meal['meal'])
                assert source_index < index < source_index + meal['storage_days']
                assert source['recipe'] == meal['recipe']
                assert source['ingredients'] == meal['ingredients']
    assert reused > 0


def test_ai_does_not_displace_an_affordable_candidate(fridge_client):
    from collections import Counter
    from app.recommender import _select_recipe
    _, engine = fridge_client
    with Session(engine) as db:
        expensive = db.query(Recipe).filter_by(name='Лосось с рисом').one()
        cheap = db.query(Recipe).filter_by(name='Гречка с курицей').one()
        result, evaluation = _select_recipe([expensive, cheap], cheap.calories,
            Counter(), cheap.estimated_cost + 1, set(), set(), ai_recipe_id=expensive.id)
        assert result.id == cheap.id
        assert 'выбрано ИИ из допустимого каталога' not in evaluation.reasons
