"""Shared restrictions for planning, catalogue and fridge recommendations.

Ingredient checks supplement catalogue allergen labels; they cannot identify
undeclared ingredients or cross-contamination in real products.
"""
import json
import re

from .recommendation_rules import is_diet_allowed, normalise_restrictions
from .recipe_catalog import RETIRED_RECIPE_NAMES


PRODUCT_GROUPS = {
    "курица": ("куриц", "курин"),
    "индейка": ("индей",),
    "помидор": ("помидор", "томат"),
    "картофель": ("картоф", "картош"),
}
ALLERGEN_INGREDIENTS = {
    "milk": ("молок", "сыр", "творог", "йогурт", "кефир", "сметан", "сливк", "сливоч"),
    "eggs": ("яйц", "яич"),
    "fish": ("рыб", "лосос", "семг", "минтай", "треск", "тунц", "тунец", "скумбр", "форел", "сельд"),
    "nuts": ("орех", "миндал", "фундук", "кешью", "фисташ", "арахис"),
    "soy": ("соев", "соя", "сои", "сою", "соей", "тофу"),
    "sesame": ("кунжут", "тахин"),
    "gluten": ("пшениц", "пшенич", "макарон", "булгур", "кускус", "хлеб", "лаваш", "тортиль", "манн", "перлов", "ржан", "ячмен", "овся", "гранол", "пита"),
}


def words(text: str) -> list[str]:
    return re.findall(r"[а-яa-z]+", text.casefold().replace("ё", "е"))


def contains_stem(text: str, stems: tuple[str, ...]) -> bool:
    return any(word.startswith(stem) for word in words(text) for stem in stems)


def ingredient_has_allergen(ingredient: str, allergen: str) -> bool:
    text = ingredient.casefold().replace("ё", "е")
    if allergen == 'milk':
        # Preparation labels such as "фарш сырой" do not denote cheese.
        text = ' '.join(w for w in words(text) if w not in {
            'сырой', 'сырая', 'сырое', 'сырые', 'сырых', 'сырого', 'сыром',
        })
    if allergen == 'fish':
        text = ' '.join(w for w in words(text) if not w.startswith('сельдере'))
    if allergen == 'nuts':
        text = text.replace('мускатный орех', '')
    if allergen == "milk" and text.strip() in {
        "кокосовое молоко", "соевое молоко", "овсяное молоко",
        "миндальное молоко", "рисовое молоко",
    }:
        # Plant drinks are checked for their own ingredients, not dairy.
        return False
    if allergen == "gluten":
        # Explicitly named flour replaces the catalogue's ambiguous "Мука".
        # An unspecified flour is excluded conservatively, while rice/corn/
        # buckwheat flour alone does not trigger the wheat restriction.
        if "безглютен" in text and not contains_stem(
            text, ("пшениц", "пшенич", "ржан", "ячмен", "перлов", "манн", "булгур", "кускус")
        ):
            return False
        if contains_stem(text, ("соев",)) and contains_stem(text, ("соус",)):
            # Ordinary shoyu contains wheat; a certified gluten-free variant
            # must be named explicitly to use the exception above.
            return True
        if contains_stem(text, ("мук",)):
            if not contains_stem(text, ("рисов", "кукуруз", "гречнев")):
                return True
    return contains_stem(text, ALLERGEN_INGREDIENTS.get(allergen, ()))


def matches_product(ingredient: str, restriction: str) -> bool:
    for stems in PRODUCT_GROUPS.values():
        if contains_stem(restriction, stems):
            return contains_stem(ingredient, stems)
    requested = words(restriction)
    actual = words(ingredient)
    return bool(requested) and all(word in actual for word in requested)


def recipe_is_compatible(recipe, diet: str, restrictions: set[str]) -> bool:
    if getattr(recipe, "name", "") in RETIRED_RECIPE_NAMES:
        return False
    if not is_diet_allowed(recipe.diet, diet):
        return False
    restrictions = normalise_restrictions(",".join(restrictions))
    if normalise_restrictions(recipe.allergens or "") & restrictions:
        return False
    if not restrictions:
        return True
    try:
        ingredients = json.loads(recipe.ingredients)
        if not isinstance(ingredients, dict):
            return False
    except (TypeError, ValueError):
        return False
    for restriction in restrictions:
        for ingredient in ingredients:
            if restriction in ALLERGEN_INGREDIENTS:
                if ingredient_has_allergen(ingredient, restriction):
                    return False
            elif matches_product(ingredient, restriction):
                return False
    return True
