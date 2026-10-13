"""Reproducible estimates from an attributed, bounded ingredient snapshot."""
import json
import math
from pathlib import Path


REFERENCE = json.loads(Path(__file__).with_name("nutrition_reference.json").read_text(encoding="utf-8"))


def calculate_nutrition(ingredients: dict[str, float]) -> dict[str, float]:
    totals = {key: 0.0 for key in ("calories", "protein", "fat", "carbs")}
    for product, grams in ingredients.items():
        if not math.isfinite(grams) or grams <= 0:
            raise ValueError("Invalid ingredient weight")
        nutrient = REFERENCE["foods"][product]  # Unknown foods must never silently count as zero.
        for key in totals:
            totals[key] += nutrient["per_100g"][key] * grams / 100
    return {key: round(value, 2) for key, value in totals.items()}
