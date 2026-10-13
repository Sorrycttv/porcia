"""Own transparent ranking model for the NutriPlan recommender.

This module is deliberately separate from the language model.  It makes the
selection of a recipe reproducible: all factors have an explicit weight and
can be shown to the user and described in the VKR.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateScore:
    """Evaluation of one candidate recipe for one planned meal."""

    score: int
    scaled_cost: float
    reasons: tuple[str, ...]


def score_recipe(
    *,
    recipe_name: str,
    recipe_calories: float,
    recipe_cost: float,
    preparation_minutes: int,
    batch_servings: int,
    meal_target: float,
    meal_budget: float | None,
    prior_uses: int,
    uses_pantry: bool = False,
    matches_preference: bool = False,
) -> CandidateScore:
    """Score a compatible recipe from 0 to 100 using weighted factors.

    Diet and allergen restrictions are hard filters and are checked before
    this function.  The ranking itself balances budget, novelty, base-portion
    fit and practical preparation time.
    """

    multiplier = meal_target / recipe_calories
    scaled_cost = recipe_cost * multiplier
    reasons: list[str] = []

    # 25 points: financial feasibility for this meal.
    if meal_budget is None:
        budget_points = 15
    elif scaled_cost <= meal_budget:
        budget_points = 25
        reasons.append("укладывается в плановую стоимость приёма пищи")
    else:
        overspend_ratio = (scaled_cost - meal_budget) / meal_budget
        budget_points = max(0, round(25 * (1 - overspend_ratio)))
        reasons.append("выбран как ближайший доступный вариант при заданном бюджете")

    # 20 points: novelty across the selected period.
    diversity_points = {0: 20, 1: 12}.get(prior_uses, 5)
    if prior_uses == 0:
        reasons.append("не повторяется в текущем плане")

    # 20 points: small adjustment of the catalogue portion is preferable.
    portion_distance = abs(recipe_calories - meal_target) / meal_target
    portion_points = max(0, round(20 * (1 - portion_distance)))
    if portion_points >= 15:
        reasons.append("базовая порция близка к целевой калорийности")

    # 10 points: quick recipes are more convenient on working days.
    time_points = 10 if preparation_minutes <= 20 else 6 if preparation_minutes <= 35 else 3
    if preparation_minutes <= 20:
        reasons.append("готовится не более 20 минут")

    # 5 points: a suitable main dish may be prepared with a reserve.
    batch_points = 5 if batch_servings > 1 else 0
    if batch_servings > 1:
        reasons.append("подходит для приготовления с запасом")

    # 10 points: a recipe that uses products already at home avoids a purchase.
    pantry_points = 10 if uses_pantry else 0
    if uses_pantry:
        reasons.insert(0, "использует продукты из домашнего запаса")

    # 10 points: explicitly requested products should influence the result.
    preference_points = 10 if matches_preference else 0
    if matches_preference:
        reasons.insert(0, "учитывает желаемые продукты")

    score = min(100, budget_points + diversity_points + portion_points + time_points + batch_points + pantry_points + preference_points)
    if not reasons:
        reasons.append(f"рецепт «{recipe_name}» соответствует заданным ограничениям")
    return CandidateScore(score=score, scaled_cost=scaled_cost, reasons=tuple(reasons[:3]))
