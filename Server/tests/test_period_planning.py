import json
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-only-secret")

from app.db import Base
from app.main import _deterministic_plan_explanation
from app.models import Profile, Recipe
from app.recipe_catalog import RECIPE_CATALOG
from app.recommender import make_period_plan, normalise_product_name


class PeriodPlanningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        wanted = {
            "Овсяная каша с ягодами",
            "Гречка с курицей",
            "Лосось с рисом",
            "Яблоко с орехами",
            "Домашняя пицца Маргарита",
        }
        for data in RECIPE_CATALOG:
            if data["name"] not in wanted:
                continue
            self.db.add(Recipe(
                name=data["name"], calories=data["calories"],
                protein=data["protein"], fat=data["fat"], carbs=data["carbs"],
                diet=data["diet"], allergens=data["allergens"],
                ingredients=json.dumps(data["ingredients"], ensure_ascii=False),
                estimated_cost=data["cost"],
                preparation_minutes=data["preparation_minutes"],
                instructions=data["instructions"], meal_slot=data["meal_slot"],
                side_dish=data["side_dish"], batch_servings=data["batch_servings"],
                storage_days=data["storage_days"],
            ))
        self.db.commit()
        self.profile = Profile(
            user_id=1, sex="male", age=27, height_cm=179, weight_kg=80,
            activity="low", goal="maintain", diet="none", restrictions="",
            preferred_foods="", target_calories=2400, monthly_budget=20000,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_variety_mode_does_not_force_leftovers(self):
        _, plans, _, _ = make_period_plan(
            self.db, self.profile, 3, cooking_mode="variety"
        )
        self.assertTrue(all(
            meal.batch_servings_to_prepare == 1
            for day in plans for meal in day
        ))

    def test_batch_mode_reuses_a_prepared_main_dish(self):
        _, plans, _, _ = make_period_plan(
            self.db, self.profile, 3, cooking_mode="batch"
        )
        self.assertTrue(any(
            meal.batch_servings_to_prepare == 0
            for day in plans[1:] for meal in day
        ))

    def test_catalogue_recipe_can_be_pinned_to_dinner(self):
        _, plans, _, _ = make_period_plan(
            self.db,
            self.profile,
            1,
            cooking_mode="variety",
            pinned_recipe="Домашняя пицца Маргарита",
            pinned_meal="dinner",
        )
        dinner = next(meal for meal in plans[0] if meal.meal == "Ужин")
        self.assertEqual(dinner.recipe.name, "Домашняя пицца Маргарита")
        self.assertIn("добавлено вами из книги блюд", dinner.selection_reasons)

    def test_common_fridge_word_forms_are_normalised(self):
        self.assertEqual(normalise_product_name("курицы"), "куриное филе")
        self.assertEqual(normalise_product_name("риса"), "рис")

    def test_explanation_uses_goal_budget_and_selection_reason(self):
        payload = {
            "period_days": 1,
            "cooking_mode": "variety",
            "target_calories": 2400,
            "estimated_period_cost": 500,
            "estimated_monthly_cost": 15000,
            "monthly_budget": 20000,
            "budget_difference": 5000,
            "pantry_used": [{"product": "Рис", "grams": 100}],
            "shopping_list": [],
            "days": [{
                "meals": [{
                    "meal": "обед", "recipe": "Гречка с курицей",
                    "calories": 840,
                    "selection_reasons": ["использует продукты из домашнего запаса"],
                }]
            }],
        }

        explanation = _deterministic_plan_explanation(payload, self.profile)

        self.assertIn("поддержание веса", explanation)
        self.assertIn("использует продукты из домашнего запаса", explanation)
        self.assertIn("5000 ₽ ниже бюджета", explanation)


if __name__ == "__main__":
    unittest.main()
