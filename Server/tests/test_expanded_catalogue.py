import json
from collections import Counter
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.expanded_recipes import EXPANDED_RECIPES
from app.food_filters import ingredient_has_allergen, recipe_is_compatible
from app.main import _meal_payload, seed_recipes
from app.models import Recipe, SavedPlan
from app.nutrition import calculate_nutrition
from app.portion_guard import portion_is_reasonable
from app.recipe_catalog import RECIPE_CATALOG, CATALOG_BY_NAME, RETIRED_RECIPE_NAMES
from app.recommender import PlannedMeal
from tests.test_fridge_flow import fridge_client


def test_sourced_additions_have_individual_provenance_and_recomputed_nutrition():
    assert Counter(r['meal_slot'] for r in RECIPE_CATALOG) == {'breakfast': 25, 'main': 36, 'snack': 18}
    assert Counter(r['meal_slot'] for r in EXPANDED_RECIPES) == {'main': 20, 'snack': 12}
    assert len({r['recipe_source_url'] for r in EXPANDED_RECIPES}) == 32
    assert len({json.dumps(r['ingredients'], sort_keys=True) for r in EXPANDED_RECIPES}) == 32
    for r in EXPANDED_RECIPES:
        assert r['recipe_source_url'].startswith('https://www.nhs.uk/healthier-families/recipes/')
        assert r['recipe_adaptation_note'] and r['source_checked_at'] == '2026-10-11'
        assert calculate_nutrition(r['ingredients']) == {k: r[k] for k in ('calories', 'protein', 'fat', 'carbs')}
        assert r['name'] not in RETIRED_RECIPE_NAMES


def test_raw_labels_celery_and_nutmeg_do_not_produce_false_allergens():
    assert not ingredient_has_allergen('Фарш индейки сырой', 'milk')
    assert not ingredient_has_allergen('Пикша филе сырое', 'milk')
    assert not ingredient_has_allergen('Сельдерей стеблевой', 'fish')
    assert not ingredient_has_allergen('Мускатный орех молотый', 'nuts')
    assert ingredient_has_allergen('Сыр чеддер пониженной жирности', 'milk')
    assert ingredient_has_allergen('Орехи кедровые', 'nuts')


def test_water_scales_with_portion_but_is_not_added_to_shopping(fridge_client):
    _, engine = fridge_client
    with Session(engine) as db:
        r = db.query(Recipe).filter_by(name='Ризотто с грибами').one()
        meal = PlannedMeal('Обед', r, 1.5, 0, ())
        payload = _meal_payload(meal)
        assert payload['cooking_water_ml'] == 337.5
        assert not any(i['product'] == 'Вода' for i in payload['ingredients'])
        assert 'мл на одну базовую' not in payload['instructions']


def test_oversized_low_density_soup_is_not_a_candidate_for_840_kcal(fridge_client):
    client, engine = fridge_client
    with Session(engine) as db:
        soup = db.query(Recipe).filter_by(name='Томатный суп с фасолью и кукурузой').one()
        assert not portion_is_reasonable(soup, 840)
        assert portion_is_reasonable(soup, soup.calories)
    result = client.post('/api/v1/plans/generate', json={
        'days': 1, 'pinned_recipe': soup.name, 'pinned_meal': 'lunch'})
    assert result.status_code == 400


@pytest.mark.parametrize('mode', ['variety', 'balanced', 'batch'])
def test_week_uses_new_catalogue_without_oversized_portions_or_same_day_mains(fridge_client, mode):
    client, _ = fridge_client
    response = client.post('/api/v1/plans/generate', json={'days': 7, 'cooking_mode': mode})
    assert response.status_code == 200, response.text
    plan = response.json()
    for day in plan['days']:
        mains = [m for m in day['meals'] if m['meal'] in ('Обед', 'Ужин')]
        assert mains[0]['recipe'] != mains[1]['recipe']
        for meal in day['meals']:
            record = CATALOG_BY_NAME[meal['recipe']]
            if 'max_portion_input_grams' in record:
                assert sum(i['grams'] for i in meal['ingredients']) + meal['cooking_water_ml'] <= record['max_portion_input_grams'] + 0.1


def test_reused_name_refreshes_in_place_and_keeps_saved_snapshot(fridge_client):
    _, engine = fridge_client
    with Session(engine) as db:
        recipe = db.query(Recipe).filter_by(name='Спагетти болоньезе').one()
        recipe_id = recipe.id
        recipe.instructions = 'Старая инструкция'
        saved = SavedPlan(user_id=1, payload='{"recipe":"Спагетти болоньезе","calories":123}')
        db.add(saved)
        db.commit()
        old_snapshot = saved.payload
        seed_recipes(db)
        assert db.get(Recipe, recipe_id).instructions == CATALOG_BY_NAME[recipe.name]['instructions']
        assert saved.payload == old_snapshot


def test_price_proxy_is_exposed_and_not_presented_as_retail_price(fridge_client):
    client, _ = fridge_client
    data = client.get('/api/v1/recipes', params={'q': 'Спагетти болоньезе'}).json()['recipes'][0]
    assert data['cost_status'] == 'unverified_planning_estimate'
    assert data['cost_method'] == 'base_catalogue_median_cost_per_kcal_by_slot_v1'
    assert 'не подтверждает экономию' in data['recipe_adaptation_note']


def test_proxy_recipe_cannot_claim_cheaper_replacement(fridge_client):
    client, _ = fridge_client
    response = client.post('/api/v1/plans/generate', json={
        'days': 1, 'pinned_recipe': 'Паста с томатами и базиликом', 'pinned_meal': 'lunch'})
    assert response.status_code == 200, response.text
    plan = response.json()
    swapped = client.post('/api/v1/plans/replace-meal', json={
        'revision': plan['revision'], 'day_index': 0, 'meal': 'Обед', 'reason': 'cheaper'})
    assert swapped.status_code == 400
    assert client.get('/api/v1/plans/current').json()['plan'] == plan


def test_new_soups_require_raw_chicken_and_include_preparation_time():
    for name in ('Куриный суп с яичной лапшой и овощами', 'Сливочный суп с курицей, картофелем и кукурузой'):
        r = CATALOG_BY_NAME[name]
        assert 'Куриное филе' in r['ingredients']
        assert 'Куриное филе запечённое' not in r['ingredients']
        assert r['preparation_minutes'] >= 40


def test_celery_restriction_excludes_quiche():
    data = CATALOG_BY_NAME['Грибной мини-киш без теста с салатом']
    recipe = SimpleNamespace(**{**data, 'ingredients': json.dumps(data['ingredients'])})
    assert not recipe_is_compatible(recipe, 'none', {'сельдерей'})
