"""Pure functions used by the daily meal-plan recommender.

The calculations are kept outside the database layer so that the rules can be
tested independently from PostgreSQL and the HTTP API.
"""

ACTIVITY_COEFFICIENTS = {
    "low": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "high": 1.725,
}

# The shares are deliberately explicit because they are shown in the VKR
# algorithm.  A small snack makes the daily plan more practical without
# turning the estimate into a medical prescription.
MEAL_DISTRIBUTION = (
    ("Завтрак", "breakfast", 0.25),
    ("Обед", "main", 0.35),
    ("Ужин", "main", 0.28),
    ("Перекус", "snack", 0.12),
)


def calculate_serving_multiplier(recipe_calories: float, meal_target: float) -> float:
    """Return the portion multiplier needed to reach a meal calorie target.

    Recipes in the catalogue describe a base serving.  The recommendation is
    made practical by scaling that serving rather than presenting three fixed
    dishes whose total can differ substantially from the daily target.
    """

    if recipe_calories <= 0:
        raise ValueError("Калорийность базовой порции должна быть положительной")
    return meal_target / recipe_calories


def calculate_target_calories(
    *,
    sex: str,
    age: int,
    height_cm: float,
    weight_kg: float,
    activity: str,
    goal: str,
) -> float:
    """Calculate daily calories using the Mifflin--St Jeor equation.

    The result is a planning estimate, not a medical prescription.  A calorie
    adjustment is applied only after the activity coefficient is considered.
    """

    basal_metabolic_rate = 10 * weight_kg + 6.25 * height_cm - 5 * age
    sex_adjustment = {"male": 5, "female": -161}.get(sex, -78)
    maintenance_calories = (
        basal_metabolic_rate + sex_adjustment
    ) * ACTIVITY_COEFFICIENTS[activity]
    goal_adjustment = {"lose": -350, "gain": 300}.get(goal, 0)

    return round(maintenance_calories + goal_adjustment)


def normalise_restrictions(values: str) -> set[str]:
    """Convert the comma-separated field stored in the database into a set."""

    import re
    aliases = {
        "рыба": "fish", "яйца": "eggs", "молоко": "milk", "глютен": "gluten",
        "орехи": "nuts", "соя": "soy", "кунжут": "sesame",
        "яйцо": "eggs", "яиц": "eggs", "молочные продукты": "milk",
        "молочный белок": "milk", "арахис": "nuts",
    }
    return {
        aliases.get(value.strip().casefold().replace("ё", "е"), value.strip().casefold().replace("ё", "е"))
        for value in re.split(r"[,;\n]", values or "")
        if value.strip()
    }


def is_diet_allowed(recipe_diet: str, selected_diet: str) -> bool:
    """Return whether a recipe satisfies the selected diet type."""

    if selected_diet == "vegan":
        return recipe_diet == "vegan"
    if selected_diet == "vegetarian":
        return recipe_diet in {"vegetarian", "vegan"}
    return True
