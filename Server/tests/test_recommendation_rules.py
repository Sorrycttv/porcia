import unittest

from app.recommendation_rules import (
    calculate_serving_multiplier,
    calculate_target_calories,
    is_diet_allowed,
    normalise_restrictions,
)
from app.recommendation_scoring import score_recipe
from app.recipe_catalog import RECIPE_CATALOG


class RecommendationRulesTests(unittest.TestCase):
    def test_catalogue_covers_a_week_without_placeholder_count_target(self):
        from collections import Counter
        slots = Counter(r["meal_slot"] for r in RECIPE_CATALOG)
        self.assertGreaterEqual(slots["breakfast"], 7)
        self.assertGreaterEqual(slots["main"], 14)
        self.assertGreaterEqual(slots["snack"], 4)
        self.assertEqual(len({r["name"] for r in RECIPE_CATALOG}), len(RECIPE_CATALOG))

    def test_calorie_target_for_maintenance_is_calculated_by_formula(self):
        calories = calculate_target_calories(
            sex="male",
            age=25,
            height_cm=175,
            weight_kg=70,
            activity="moderate",
            goal="maintain",
        )

        self.assertEqual(calories, 2594)

    def test_weight_loss_goal_reduces_calorie_target(self):
        maintenance = calculate_target_calories(
            sex="female",
            age=30,
            height_cm=165,
            weight_kg=65,
            activity="light",
            goal="maintain",
        )
        weight_loss = calculate_target_calories(
            sex="female",
            age=30,
            height_cm=165,
            weight_kg=65,
            activity="light",
            goal="lose",
        )

        self.assertEqual(maintenance - weight_loss, 350)

    def test_restrictions_are_normalised_before_comparison(self):
        self.assertEqual(normalise_restrictions(" Рыба, яйца,РЫБА "), {"fish", "eggs"})

    def test_vegetarian_diet_accepts_vegan_recipe(self):
        self.assertTrue(is_diet_allowed("vegan", "vegetarian"))
        self.assertFalse(is_diet_allowed("none", "vegetarian"))

    def test_serving_multiplier_matches_the_meal_target(self):
        multiplier = calculate_serving_multiplier(560, 986.4)

        self.assertAlmostEqual(multiplier, 1.7614285714)
        self.assertAlmostEqual(560 * multiplier, 986.4)

    def test_own_ranking_rewards_budget_and_new_recipe(self):
        evaluation = score_recipe(
            recipe_name="Тестовое блюдо",
            recipe_calories=500,
            recipe_cost=100,
            preparation_minutes=15,
            batch_servings=2,
            meal_target=500,
            meal_budget=120,
            prior_uses=0,
        )

        self.assertEqual(evaluation.score, 80)
        self.assertIn("не повторяется в текущем плане", evaluation.reasons)

    def test_own_ranking_rewards_products_already_at_home(self):
        evaluation = score_recipe(
            recipe_name="Тестовое блюдо",
            recipe_calories=500,
            recipe_cost=100,
            preparation_minutes=15,
            batch_servings=2,
            meal_target=500,
            meal_budget=120,
            prior_uses=0,
            uses_pantry=True,
        )

        self.assertEqual(evaluation.score, 90)
        self.assertIn("использует продукты из домашнего запаса", evaluation.reasons)

    def test_own_ranking_rewards_requested_ingredient(self):
        evaluation = score_recipe(
            recipe_name="Паста с индейкой",
            recipe_calories=500,
            recipe_cost=100,
            preparation_minutes=15,
            batch_servings=2,
            meal_target=500,
            meal_budget=120,
            prior_uses=0,
            matches_preference=True,
        )

        self.assertEqual(evaluation.score, 90)
        self.assertIn("учитывает желаемые продукты", evaluation.reasons)



if __name__ == "__main__":
    unittest.main()
