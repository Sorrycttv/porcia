"""Основной алгоритм формирования рациона NutriPlan.

Алгоритм не является «чёрным ящиком»: он отбрасывает несовместимые блюда,
ранжирует оставшиеся по прозрачной функции, рассчитывает порции и собирает
список покупок. Выбор языковой модели учитывается только среди допустимых
кандидатов после проверок ограничений, разнообразия и плановой стоимости.
"""

import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .models import Profile, Recipe
from .food_filters import recipe_is_compatible
from .portion_guard import portion_is_reasonable
from .recommendation_rules import (
    MEAL_DISTRIBUTION,
    calculate_serving_multiplier,
    calculate_target_calories,
    normalise_restrictions,
)
from .recommendation_scoring import CandidateScore, score_recipe


_PRODUCT_ALIASES = {
    "курица": "куриное филе",
    "курицы": "куриное филе",
    "курицу": "куриное филе",
    "куриного филе": "куриное филе",
    "индейка": "филе индейки",
    "индейки": "филе индейки",
    "картошка": "картофель",
    "картошки": "картофель",
    "картофеля": "картофель",
    "яйцо": "яйца",
    "риса": "рис",
    "молока": "молоко",
    "рисовая крупа": "рис",
}


def normalise_product_name(value: str) -> str:
    """Normalise common everyday product names used in the fridge input."""

    cleaned = " ".join(value.strip().casefold().replace("ё", "е").split())
    return _PRODUCT_ALIASES.get(cleaned, cleaned)


@dataclass(frozen=True)
class PlannedMeal:
    """A selected base recipe together with its calculated serving size."""

    meal: str
    recipe: Recipe
    portion_multiplier: float
    selection_score: int
    selection_reasons: tuple[str, ...]
    batch_servings_to_prepare: int = 1
    prepared_on_day: int | None = None
    is_surprise: bool = False

    @property
    def calories(self) -> float:
        return self.recipe.calories * self.portion_multiplier

    @property
    def protein(self) -> float:
        return self.recipe.protein * self.portion_multiplier

    @property
    def fat(self) -> float:
        return self.recipe.fat * self.portion_multiplier

    @property
    def carbs(self) -> float:
        return self.recipe.carbs * self.portion_multiplier

    @property
    def estimated_cost(self) -> float:
        return self.recipe.estimated_cost * self.portion_multiplier

    @property
    def portion_percent(self) -> int:
        return round(self.portion_multiplier * 100)

    @property
    def portion_weight_grams(self) -> int:
        """Approximate edible mass calculated from the ingredient list."""

        try:
            ingredients = json.loads(self.recipe.ingredients)
        except json.JSONDecodeError:
            return 0
        return round(sum(float(grams) for grams in ingredients.values()) * self.portion_multiplier / 10) * 10


# --- Проверка совместимости и выбор одного блюда -------------------------

def target_calories(profile: Profile) -> float:
    """Return either the user target or the calculated daily estimate."""

    if profile.target_calories:
        return profile.target_calories
    return calculate_target_calories(
        sex=profile.sex,
        age=profile.age,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        activity=profile.activity,
        goal=profile.goal,
    )


def _is_compatible(recipe: Recipe, profile: Profile, restrictions: set[str]) -> bool:
    """Check diet and declared allergens before a recipe is considered."""

    return recipe_is_compatible(recipe, profile.diet, restrictions)


def _select_recipe(
    recipes: list[Recipe],
    target: float,
    usage_counts: Counter[str],
    meal_budget: float | None,
    pantry_products: set[str],
    desired_products: set[str],
    surprise: bool = False,
    ai_recipe_id: int | None = None,
) -> tuple[Recipe, CandidateScore]:
    """Select the best recipe using the application's own weighted model."""

    evaluations = [
        (
            recipe,
            score_recipe(
                recipe_name=recipe.name,
                recipe_calories=recipe.calories,
                recipe_cost=recipe.estimated_cost,
                preparation_minutes=recipe.preparation_minutes,
                batch_servings=recipe.batch_servings,
                meal_target=target,
                meal_budget=meal_budget,
                prior_uses=usage_counts[recipe.name],
                uses_pantry=bool(_recipe_products(recipe).intersection(pantry_products)),
                matches_preference=_recipe_matches_preference(recipe, desired_products),
            ),
        )
        for recipe in recipes
    ]
    # A feasible meal stays ahead of a more expensive one even if it would
    # otherwise get a slightly higher convenience score.
    ranked = sorted(
        evaluations,
        key=lambda item: (
            meal_budget is not None and item[1].scaled_cost > meal_budget,
            -item[1].score,
            item[0].name,
        ),
    )
    if surprise and len(ranked) > 1:
        # The surprise still passes every hard filter. It is chosen at random
        # from quick, visually interesting catalogue dishes, not from an
        # arbitrary or medically unsuitable option.
        surprise_candidates = [item for item in ranked if _is_fun_surprise(item[0])]
        pool = surprise_candidates[:5] or ranked[1:min(6, len(ranked))]
        recipe, score = random.SystemRandom().choice(pool)
        return recipe, CandidateScore(
            score=score.score,
            scaled_cost=score.scaled_cost,
            reasons=("«Удивить себя»: вкусный быстрый рецепт из интересной подборки",) + score.reasons,
        )
    if ai_recipe_id is not None:
        feasible = [item for item in ranked if meal_budget is None or item[1].scaled_cost <= meal_budget]
        pool = feasible or ranked
        fewest_uses = min(usage_counts[recipe.name] for recipe, _ in pool)
        for recipe, score in pool:
            if recipe.id == ai_recipe_id and usage_counts[recipe.name] == fewest_uses:
                return recipe, CandidateScore(score.score, score.scaled_cost,
                    ("выбрано ИИ из допустимого каталога",) + score.reasons)
    return ranked[0]


def _recipe_products(recipe: Recipe) -> set[str]:
    """Return normalised ingredient names for a recipe."""

    try:
        return {normalise_product_name(product) for product in json.loads(recipe.ingredients)}
    except json.JSONDecodeError:
        return set()


def _recipe_matches_preference(recipe: Recipe, desired_products: set[str]) -> bool:
    """Match requested products, including a few everyday Russian aliases."""

    if not desired_products:
        return False
    recipe_terms = _recipe_products(recipe) | {recipe.name.casefold()}
    aliases = {
        "паста": {"паста", "макароны"},
        "картошка": {"картофель"},
        "картошка фри": {"картофель"},
        "курица": {"куриное филе"},
        "индейка": {"филе индейки"},
    }
    for desired in desired_products:
        variants = aliases.get(desired, {desired})
        if any(variant in term or term in variant for variant in variants for term in recipe_terms):
            return True
    return False


def _is_fun_surprise(recipe: Recipe) -> bool:
    """A curated set for the optional single 'surprise me' dinner."""

    keywords = (
        "пицца", "бургер", "буррито", "тако", "боул", "поке", "вок", "фахитас",
        "кесадилья", "роллы", "паста", "шаверма", "рамэн", "удон", "нагь",
    )
    return recipe.preparation_minutes <= 35 and any(
        keyword in recipe.name.casefold() for keyword in keywords
    )


# --- Рацион на один день и список продуктов ------------------------------

def make_plan(
    db: Session,
    profile: Profile,
    usage_counts: Counter[str] | None = None,
    pantry_products: set[str] | None = None,
    desired_products: set[str] | None = None,
    batch_meals: set[str] | None = None,
    surprise_meal: str | None = None,
    pinned_recipes: dict[str, str] | None = None,
    prepared_meals: dict[str, PlannedMeal] | None = None,
    previous_main_recipes: set[str] | None = None,
    ai_recipes: dict[str, int] | None = None,
) -> tuple[float, list[PlannedMeal]]:
    """Build four meals, reserving prepared/pinned dishes before selection."""

    restrictions = normalise_restrictions(profile.restrictions)
    candidates = [
        recipe
        for recipe in db.query(Recipe).all()
        if _is_compatible(recipe, profile, restrictions)
    ]
    if not candidates:
        raise ValueError("В каталоге нет блюд, подходящих под выбранные ограничения")

    daily_calories = target_calories(profile)
    usage_counts = usage_counts if usage_counts is not None else Counter()
    pantry_products = pantry_products if pantry_products is not None else set()
    desired_products = desired_products if desired_products is not None else set()
    batch_meals = batch_meals if batch_meals is not None else set()
    pinned_recipes = pinned_recipes if pinned_recipes is not None else {}
    prepared_meals = prepared_meals or {}
    previous_main_recipes = previous_main_recipes or set()
    plan: list[PlannedMeal] = []
    for meal_name, meal_slot, calorie_share in MEAL_DISTRIBUTION:
        if meal_name in prepared_meals:
            prepared = prepared_meals[meal_name]
            usage_counts[prepared.recipe.name] += 1
            plan.append(prepared)
            continue
        slot_candidates = [
            recipe for recipe in candidates if recipe.meal_slot == meal_slot
        ]
        if not slot_candidates:
            raise ValueError(
                f"В каталоге нет подходящих блюд для приёма пищи «{meal_name}» с выбранными ограничениями"
            )
        meal_target = daily_calories * calorie_share
        slot_candidates = [r for r in slot_candidates if portion_is_reasonable(r, meal_target)]
        if not slot_candidates:
            raise ValueError(f'Нет блюда с подходящим размером порции для «{meal_name}». Измените ограничения или калорийную цель')
        meal_budget = (
            profile.monthly_budget / 30 * calorie_share
            if profile.monthly_budget is not None
            else None
        )
        pinned_name = pinned_recipes.get(meal_name)
        diversity_reasons: list[str] = []
        if meal_slot == "main" and not pinned_name:
            reserved = {m.recipe.name for m in plan if m.recipe.meal_slot == "main"}
            reserved.update(m.recipe.name for key, m in prepared_meals.items() if key != meal_name)
            reserved.update(name for key, name in pinned_recipes.items() if key != meal_name)
            distinct = [r for r in slot_candidates if r.name.casefold() not in {n.casefold() for n in reserved}]
            if distinct:
                slot_candidates = distinct
            else:
                diversity_reasons.append("Недостаточно совместимых блюд: обед и ужин повторяются")
            fresh = [r for r in slot_candidates if r.name not in previous_main_recipes]
            if fresh:
                slot_candidates = fresh
            elif previous_main_recipes:
                diversity_reasons.append("Недостаточно совместимых блюд для меню без повторов в соседние дни")
        # Variety takes precedence over batch convenience; pinned dishes remain selectable.
        if meal_name in batch_meals and meal_name != surprise_meal and not pinned_name:
            batch_candidates = [r for r in slot_candidates if r.batch_servings > 1]
            if batch_candidates:
                slot_candidates = batch_candidates
        evaluated_candidates = slot_candidates
        if pinned_name:
            evaluated_candidates = [
                recipe for recipe in slot_candidates
                if recipe.name.casefold() == pinned_name.casefold()
            ]
            if not evaluated_candidates:
                raise ValueError(
                    f"Блюдо «{pinned_name}» нельзя поставить в приём пищи «{meal_name}» "
                    "с учётом выбранного типа питания и ограничений"
                )
        recipe, evaluation = _select_recipe(
            evaluated_candidates,
            meal_target,
            usage_counts,
            meal_budget,
            pantry_products,
            desired_products,
            surprise=meal_name == surprise_meal,
            ai_recipe_id=(ai_recipes or {}).get(meal_name) if not pinned_name else None,
        )
        if pinned_name:
            evaluation = CandidateScore(
                score=evaluation.score,
                scaled_cost=evaluation.scaled_cost,
                reasons=("добавлено вами из книги блюд",) + evaluation.reasons[:2],
            )
        if diversity_reasons:
            evaluation = CandidateScore(evaluation.score, evaluation.scaled_cost,
                                        tuple(diversity_reasons) + evaluation.reasons)
        usage_counts[recipe.name] += 1
        portion_multiplier = calculate_serving_multiplier(recipe.calories, meal_target)
        plan.append(
            PlannedMeal(
                meal_name,
                recipe,
                portion_multiplier,
                evaluation.score,
                evaluation.reasons,
                is_surprise=meal_name == surprise_meal,
            )
        )
    return daily_calories, plan


def shopping_list_for(
    plans: list[list[PlannedMeal]], pantry: dict[str, float] | None = None
) -> tuple[list[dict[str, int | str]], list[dict[str, int | str]]]:
    """Aggregate ingredients and subtract the quantities available at home."""

    totals: Counter[str] = Counter()
    used_in: dict[str, set[str]] = defaultdict(set)
    for day_plan in plans:
        for meal in day_plan:
            try:
                ingredients = json.loads(meal.recipe.ingredients)
            except json.JSONDecodeError:
                ingredients = {}
            for ingredient, grams in ingredients.items():
                totals[ingredient] += float(grams) * meal.portion_multiplier
                used_in[ingredient].add(meal.recipe.name)
    normalised_pantry: Counter[str] = Counter()
    for product, grams in (pantry or {}).items():
        normalised_pantry[normalise_product_name(product)] += grams
    pantry = normalised_pantry
    purchases: list[dict[str, int | str]] = []
    pantry_used: list[dict[str, int | str]] = []
    for product, grams in sorted(totals.items()):
        available = pantry.get(normalise_product_name(product), 0)
        used = min(available, grams)
        pantry[normalise_product_name(product)] -= used
        remaining = grams - used
        if used:
            pantry_used.append({"product": product, "grams": round(used, 3)})
        if remaining:
            needed = math.ceil(remaining - 1e-9)
            # Package advice is intentionally approximate: it explains why a
            # purchase can be larger than the amount used by the current plan.
            package = _suggested_package_grams(product, needed)
            packages = max(1, math.ceil(needed / package))
            purchases.append({
                "product": product,
                "grams": needed,
                "package_grams": package,
                "packages_to_buy": packages,
                "expected_leftover_grams": max(0, packages * package - needed),
                "used_in": sorted(used_in[product])[:4],
            })
    return purchases, pantry_used


def _suggested_package_grams(product: str, needed: float) -> int:
    """Return an approximate fixed retail pack size, independent of the period."""

    name = product.casefold()
    common = {
        "хумус": 200, "йогурт": 180, "творог": 180, "сыр": 200,
        "молоко": 900, "кефир": 900, "сметана": 300, "яйца": 600,
        "хлеб": 350, "лаваш": 250, "тортилья": 250, "фасоль": 400,
        "нут": 400, "кукуруза": 340, "тунец": 185,
    }
    base = next((size for key, size in common.items() if key in name), 500)
    return base


# --- План на период с учётом заготовок ----------------------------------

def make_period_plan(
    db: Session,
    profile: Profile,
    days: int,
    pantry: dict[str, float] | None = None,
    desired_products: set[str] | None = None,
    surprise_me: bool = False,
    cooking_mode: str = "variety",
    pinned_recipe: str | None = None,
    pinned_meal: str | None = None,
    ai_choices: dict[int, dict[str, int]] | None = None,
) -> tuple[float, list[list[PlannedMeal]], list[dict[str, int | str]], list[dict[str, int | str]]]:
    """Create a period plan with a user-selected cooking strategy."""

    if cooking_mode not in {"variety", "balanced", "batch"}:
        raise ValueError("Неизвестный режим готовки")
    meal_names = {
        "breakfast": "Завтрак",
        "lunch": "Обед",
        "dinner": "Ужин",
        "snack": "Перекус",
    }
    if pinned_recipe and pinned_meal not in meal_names:
        raise ValueError("Для блюда из каталога выберите приём пищи")

    usage_counts: Counter[str] = Counter()
    period_plans: list[list[PlannedMeal]] = []
    daily_calories = target_calories(profile)
    pantry = pantry or {}
    pantry_products = {
        normalise_product_name(product)
        for product, grams in pantry.items()
        if grams > 0
    }
    desired_products = desired_products or set()
    leftovers: dict[str, list[PlannedMeal]] = defaultdict(list)
    for day_index in range(days):
        batch_meals = (
            {"Обед", "Ужин"}
            if cooking_mode == "batch"
            else {"Обед"} if cooking_mode == "balanced" else set()
        )
        pinned_recipes = (
            {meal_names[pinned_meal]: pinned_recipe}
            if day_index == 0 and pinned_recipe and pinned_meal
            else {}
        )
        prepared_meals = {}
        for meal_name, remaining in leftovers.items():
            if remaining:
                prepared = remaining.pop(0)
                prepared_meals[meal_name] = PlannedMeal(
                    meal=meal_name, recipe=prepared.recipe,
                    portion_multiplier=prepared.portion_multiplier,
                    selection_score=prepared.selection_score,
                    selection_reasons=(f"приготовлено в день {prepared.prepared_on_day + 1}; используется готовая порция",),
                    batch_servings_to_prepare=0, prepared_on_day=prepared.prepared_on_day,
                )
        previous_mains = {
            m.recipe.name for m in period_plans[-1] if m.recipe.meal_slot == "main"
        } if cooking_mode == "variety" and period_plans else set()
        _, generated = make_plan(
            db,
            profile,
            usage_counts,
            pantry_products,
            desired_products,
            batch_meals=batch_meals if days - day_index > 1 else set(),
            surprise_meal=("Обед" if pinned_meal == "dinner" else "Ужин")
            if surprise_me and day_index == 0
            else None,
            pinned_recipes=pinned_recipes,
            prepared_meals=prepared_meals,
            previous_main_recipes=previous_mains,
            ai_recipes=(ai_choices or {}).get(day_index),
        )
        day_plan: list[PlannedMeal] = []
        for meal in generated:
            if meal.batch_servings_to_prepare == 0:
                day_plan.append(meal)
                continue

            if (
                meal.meal in batch_meals
                and meal.recipe.batch_servings > 1
                and not meal.is_surprise
            ):
                strategy_limit = 2 if cooking_mode == "balanced" else 3
                batch_size = min(
                    meal.recipe.batch_servings,
                    max(1, meal.recipe.storage_days),
                    strategy_limit,
                    days - day_index,
                )
                meal = PlannedMeal(
                    meal=meal.meal,
                    recipe=meal.recipe,
                    portion_multiplier=meal.portion_multiplier,
                    selection_score=meal.selection_score,
                    selection_reasons=meal.selection_reasons,
                    batch_servings_to_prepare=batch_size,
                    prepared_on_day=day_index,
                    is_surprise=False,
                )
                leftovers[meal.meal].extend([meal] * (batch_size - 1))
            day_plan.append(meal)
        period_plans.append(day_plan)
    shopping_list, pantry_used = shopping_list_for(period_plans, pantry)
    return daily_calories, period_plans, shopping_list, pantry_used
