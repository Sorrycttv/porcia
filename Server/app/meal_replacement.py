"""Replace one cooking batch without regenerating the rest of the saved menu."""
import copy
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from .food_filters import recipe_is_compatible
from .recommendation_rules import normalise_restrictions, calculate_serving_multiplier
from .recommender import PlannedMeal, shopping_list_for, normalise_product_name, _recipe_products
from .menu_ai import recommend_replacement
from .portion_guard import portion_is_reasonable
from .recipe_catalog import CATALOG_BY_NAME


def profile_signature(profile):
    values = {key: getattr(profile, key) for key in (
        'sex', 'age', 'height_cm', 'weight_kg', 'activity', 'goal', 'diet',
        'restrictions', 'preferred_foods', 'target_calories', 'monthly_budget')}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def replace_meal(payload, profile, recipes, day_index, meal_name, reason, base_url, model, serialize):
    if payload.get('period_days') not in (1, 7) or 'generation_context' not in payload:
        raise ValueError('Пересоздайте рацион: у старого плана нет исходных данных для замены')
    context = payload['generation_context']
    if context['profile_signature'] != profile_signature(profile):
        raise ValueError('Профиль изменился. Сформируйте новый рацион с актуальными ограничениями')
    if day_index >= len(payload['days']):
        raise ValueError('День отсутствует в плане')
    old = next((m for m in payload['days'][day_index]['meals'] if m['meal'] == meal_name), None)
    if old is None:
        raise ValueError('Приём пищи отсутствует в плане')
    origin = old.get('prepared_on_day')
    origin = day_index if origin is None else origin
    group = [(i, j) for i, day in enumerate(payload['days']) for j, m in enumerate(day['meals'])
             if m['meal'] == meal_name and (m.get('prepared_on_day') if m.get('prepared_on_day') is not None else i) == origin]
    slot = {'Завтрак': 'breakfast', 'Обед': 'main', 'Ужин': 'main', 'Перекус': 'snack'}[meal_name]
    restrictions = normalise_restrictions(profile.restrictions)
    candidates = [r for r in recipes if r.name != old['recipe'] and r.meal_slot == slot
                  and r.calories > 0 and recipe_is_compatible(r, profile.diet, restrictions)]
    if len(group) > 1:
        span = max(i for i, _ in group) - origin + 1
        candidates = [r for r in candidates if r.batch_servings >= len(group) and r.storage_days >= span]
    # Exclude the other main dish on every affected day before asking the model.
    if slot == 'main':
        other = {m['recipe'] for i, _ in group for m in payload['days'][i]['meals']
                 if m['meal'] in ('Обед', 'Ужин') and m['meal'] != meal_name}
        candidates = [r for r in candidates if r.name not in other]
        if payload.get('cooking_mode') == 'variety':
            neighbours = {m['recipe'] for i, _ in group for n in (i-1, i+1)
                          if 0 <= n < len(payload['days']) for m in payload['days'][n]['meals']
                          if m['meal'] in ('Обед', 'Ужин')}
            candidates = [r for r in candidates if r.name not in neighbours]
    target = old['calories']
    candidates = [r for r in candidates if all(
        portion_is_reasonable(r, payload['days'][i]['meals'][j]['calories']) for i, j in group)]
    pantry = {normalise_product_name(k): v for k, v in context['pantry'].items()}
    def cost(r): return r.estimated_cost * calculate_serving_multiplier(r.calories, target)
    if reason == 'cheaper':
        candidates = [r for r in candidates if
                      not CATALOG_BY_NAME.get(r.name, {}).get('cost_method')
                      and not CATALOG_BY_NAME.get(old['recipe'], {}).get('cost_method')
                      and round(cost(r)) < old['estimated_cost']]
    elif reason == 'faster':
        candidates = [r for r in candidates if r.preparation_minutes < old['preparation_minutes']]
    elif reason == 'pantry':
        candidates = [r for r in candidates if _recipe_products(r) & {p for p, g in pantry.items() if g > 0}]
    if not candidates:
        raise ValueError('Подходящей замены с этими условиями нет. Попробуйте другой вариант')
    used_names = [m['recipe'] for d in payload['days'] for m in d['meals']]
    recipe_id, status = recommend_replacement(candidates, reason, target, pantry, used_names, base_url, model)
    selected = next((r for r in candidates if r.id == recipe_id), None)
    if selected is None:
        selected = min(candidates, key=lambda r: (
            r.preparation_minutes if reason == 'faster' else cost(r), used_names.count(r.name), r.name))
    result = copy.deepcopy(payload)
    for i, j in group:
        previous = payload['days'][i]['meals'][j]
        planned = PlannedMeal(meal_name, selected, calculate_serving_multiplier(selected.calories, previous['calories']),
            0, ('выбрано ИИ из допустимого каталога',) if status == 'applied' else ('замена по правилам приложения',),
            batch_servings_to_prepare=len(group) if i == origin else 0, prepared_on_day=origin)
        result['days'][i]['meals'][j] = serialize(planned)
    # Ingredients of untouched meals are snapshots: catalogue edits cannot change them here.
    plans = [[PlannedMeal(m['meal'], SimpleNamespace(name=m['recipe'], ingredients=json.dumps(
        {x['product']: x['grams'] for x in m['ingredients']})), 1, 0, ()) for m in d['meals']] for d in result['days']]
    shopping, used = shopping_list_for(plans, context['pantry'])
    result['shopping_list'], result['pantry_used'] = shopping, used
    result['weekly_shopping'] = [{'start_day': 1, 'end_day': result['period_days'], 'items': shopping}]
    for i in {i for i, _ in group}:
        d = result['days'][i]
        d['estimated_cost'] = round(sum(m['estimated_cost_unrounded'] for m in d['meals']))
    result['estimated_period_cost'] = sum(d['estimated_cost'] for d in result['days'])
    result['estimated_monthly_cost'] = round(result['estimated_period_cost'] / result['period_days'] * 30)
    result['budget_difference'] = (round(result['monthly_budget'] - result['estimated_monthly_cost'])
                                   if result.get('monthly_budget') is not None else None)
    result['meals'] = result['days'][0]['meals']
    result['warnings'] = sorted({reason for d in result['days'] for m in d['meals']
        for reason in m.get('selection_reasons', []) if reason.startswith('Недостаточно совместимых блюд')})
    if any(m.get('nutrition_status') != 'ingredient_estimate' for d in result['days'] for m in d['meals']):
        result['warnings'].append('Калорийность и БЖУ части блюд пока не пересчитаны по ингредиентам. Значения ориентировочные.')
    ai = result['ai_selection']
    ai['applied_meals'] = sum('выбрано ИИ из допустимого каталога' in m.get('selection_reasons', [])
        for d in result['days'] for m in d['meals'] if m.get('time_kind') != 'reheat')
    ai['status'] = 'applied' if ai['applied_meals'] else 'not_applied'
    result['revision'] = str(uuid4())
    result['replacement'] = {'ai_status': status, 'affected_days': [i+1 for i, _ in group],
        'message': 'Связанные порции заменены; закупка пересчитана.' if len(group)>1 else 'Блюдо заменено; закупка пересчитана.'}
    return result, group
