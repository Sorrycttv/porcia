"""Editorial portion guard for sourced additions, not a medical serving limit."""
import json
from .recipe_catalog import CATALOG_BY_NAME
from .recommendation_rules import calculate_serving_multiplier


def portion_is_reasonable(recipe, target):
    record = CATALOG_BY_NAME.get(recipe.name, {})
    limit = record.get('max_portion_input_grams')
    if limit is None:
        return True
    if recipe.calories <= 0:
        return False
    try:
        mass = sum(float(v) for v in json.loads(recipe.ingredients).values())
    except (TypeError, ValueError):
        return False
    mass += record.get('cooking_water_ml', 0)
    return mass * calculate_serving_multiplier(recipe.calories, target) <= limit
