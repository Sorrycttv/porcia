"""Editable catalogue with reproducible ingredient-based nutrition estimates.

All quantities are edible portions in the ingredient's named preparation state.
Costs remain historical planning estimates, not current retailer prices.
"""
from .base_recipes import BASE_RECIPES
from .curated_recipes import CURATED_RECIPES
from .expanded_recipes import EXPANDED_RECIPES
from statistics import median

RECIPE_CATALOG = [dict(recipe) for recipe in BASE_RECIPES]

_EXTRA_BREAKFASTS = ['Гречневая каша с яблоком', 'Пшённая каша с тыквой', 'Сырники в духовке', 'Тост с авокадо и яйцом', 'Яичница с томатами', 'Рисовая каша с бананом', 'Запеканка творожная', 'Чиа-пудинг с манго', 'Овсяноблин с сыром', 'Бутерброд с индейкой', 'Кукурузная каша с сыром', 'Йогурт с бананом и семенами', 'Шакшука', 'Каша булгур с фруктами', 'Творожные вафли', 'Сэндвич с яйцом и овощами', 'Смузи-боул с ягодами', 'Панкейки овсяные', 'Мюсли с кефиром', 'Омлет с брокколи']

_EXTRA_SNACKS = ['Груша с творогом', 'Финики с орехами', 'Йогурт с ягодами', 'Апельсин и миндаль', 'Хлебцы с хумусом', 'Сыр с виноградом', 'Протеиновый коктейль', 'Капрезе мини', 'Печёное яблоко', 'Огурцы с творожным сыром', 'Попкорн без масла', 'Киви с йогуртом', 'Тост с арахисовой пастой', 'Морковный смузи']

_EXTRA_MAINS = ['Курица терияки с рисом', 'Гуляш из говядины с гречкой', 'Фрикадельки с пюре', 'Запечённая курица с картофелем', 'Рыбные котлеты с рисом', 'Плов с курицей', 'Лазанья овощная', 'Спагетти болоньезе', 'Паста карбонара облегчённая', 'Паста с грибами', 'Паста с томатами и базиликом', 'Картофель по-деревенски с курицей', 'Картофель фри в духовке с рыбой', 'Драники с грибами', 'Овощи вок с курицей', 'Булгур с индейкой', 'Кускус с овощами', 'Перловка с грибами', 'Тушёная капуста с мясом', 'Суп-пюре из тыквы', 'Борщ с курицей', 'Щи с говядиной', 'Томатный суп с фасолью', 'Чили кон карне', 'Котлеты из индейки с гречкой', 'Куриные котлеты с пюре', 'Шаурма домашняя с курицей', 'Тако с говядиной', 'Ролл с тофу и овощами', 'Запечённые овощи с сыром', 'Ризотто с грибами', 'Паэлья с морепродуктами', 'Соба с овощами', 'Лапша с курицей', 'Фалафель с питой', 'Кесадилья с курицей', 'Рагу из чечевицы', 'Картофельная запеканка с фаршем', 'Печёночные оладьи с гречкой', 'Голубцы ленивые']

_EXTRA_FAVORITES = ['Домашняя пицца Маргарита', 'Домашняя пицца с курицей и грибами', 'Пицца на лаваше с овощами', 'Мини-пиццы на тостах', 'Бургер с курицей и овощами', 'Домашние наггетсы с картофелем', 'Кесадилья с сыром и томатами', 'Запечённые роллы с лососем', 'Боул с лососем', 'Поке с курицей', 'Рамен домашний', 'Удон с говядиной', 'Фахитас с курицей', 'Вок с креветками', 'Запечённая паста с сыром', 'Сырные палочки с соусом', 'Овощной тарт', 'Хачапури ленивое', 'Домашняя шаверма с индейкой', 'Картофельные дольки с соусом']

_corrected_names = {r["name"] for r in CURATED_RECIPES + EXPANDED_RECIPES}
RETIRED_RECIPE_NAMES = (set(_EXTRA_BREAKFASTS + _EXTRA_SNACKS + _EXTRA_MAINS + _EXTRA_FAVORITES)
                        - _corrected_names)
_original_costs = {r["name"]: r["cost"] for r in RECIPE_CATALOG}
_original_costs.update({"Гречневая каша с яблоком": 70, "Пшённая каша с тыквой": 95, "Сырники в духовке": 120, "Тост с авокадо и яйцом": 145, "Яичница с томатами": 170, "Рисовая каша с бананом": 195, "Запеканка творожная": 220, "Чиа-пудинг с манго": 245, "Овсяноблин с сыром": 70, "Бутерброд с индейкой": 95, "Кукурузная каша с сыром": 120, "Йогурт с бананом и семенами": 145, "Шакшука": 170, "Каша булгур с фруктами": 195, "Творожные вафли": 220, "Сэндвич с яйцом и овощами": 245, "Смузи-боул с ягодами": 70, "Панкейки овсяные": 95, "Мюсли с кефиром": 120, "Омлет с брокколи": 145, "Домашняя пицца Маргарита": 120})
for recipe in CURATED_RECIPES:
    corrected = dict(recipe)
    corrected["cost"] = _original_costs[recipe["name"]]
    corrected["cost_status"] = "unverified_planning_estimate"
    RECIPE_CATALOG.append(corrected)
# Keep the existing planning-cost scale without inventing retailer offers.
# This is a reproducible proxy per calorie from the original base catalogue;
# it cannot establish which new recipe is actually cheaper at a store.
_planning_rates = {
    slot: median(r['cost'] / r['calories'] for r in BASE_RECIPES
                 if r['meal_slot'] == slot and r['calories'] > 0)
    for slot in {r['meal_slot'] for r in EXPANDED_RECIPES}
}
for recipe in EXPANDED_RECIPES:
    expanded = dict(recipe)
    expanded['cost'] = round(recipe['calories'] * _planning_rates[recipe['meal_slot']], 2)
    expanded['cost_status'] = 'unverified_planning_estimate'
    expanded['cost_method'] = 'base_catalogue_median_cost_per_kcal_by_slot_v1'
    RECIPE_CATALOG.append(expanded)
CATALOG_BY_NAME = {r["name"]: r for r in RECIPE_CATALOG}


def nutrition_metadata(name: str) -> dict:
    recipe = CATALOG_BY_NAME.get(name, {})
    return {"nutrition_status": recipe.get("nutrition_status", "unverified_estimate"),
            "nutrition_source": recipe.get("nutrition_source", "Прежняя демонстрационная оценка; ещё не пересчитано"),
            "weight_basis": "ingredients_before_cooking",
            "cost_status": recipe.get('cost_status', 'unverified_planning_estimate'),
            **{key: recipe[key] for key in (
                'recipe_source_url', 'recipe_source_name', 'recipe_adaptation_note',
                'storage_note', 'storage_source_url', 'source_checked_at', 'cost_method', 'cooking_water_ml',
            ) if key in recipe}}
