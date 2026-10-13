package ru.pershin.nutriplan

import org.junit.Assert.assertEquals
import org.junit.Test

class PlanCookingDetailsTest {
    private fun meal(name: String = "Обед", origin: Int? = null, grams: Double = 100.0) = PlanMeal(
        meal = name, recipe = "Курица с рисом", portionWeightGrams = 200, calories = 500,
        estimatedCost = 100, displayMinutes = 20, timeKind = "cook", preparedOnDay = origin,
        ingredients = listOf(RecipeIngredient("Рис", grams)), instructions = "Приготовить")

    private fun plan(vararg meals: List<PlanMeal>) = PlanResponse(
        periodDays = meals.size, targetCalories = 2000.0,
        days = meals.map { PlanDay("2026-10-12", it, 100) }, shoppingList = emptyList(),
        estimatedPeriodCost = 100, estimatedMonthlyCost = 3000)

    @Test fun batchSumsDifferentPortionSizesInsteadOfMultiplyingFirstPortion() {
        val first = meal(origin = 0, grams = 150.0).copy(batchServingsToPrepare = 2)
        val reheat = meal(origin = 0, grams = 120.0).copy(timeKind = "reheat", batchServingsToPrepare = 0)
        val batch = PlanCookingDetails.batch(plan(listOf(first), listOf(reheat)), 1, reheat)
        assertEquals(0, batch.preparedOnDay)
        assertEquals(2, batch.portions)
        assertEquals(270.0, batch.ingredients.single().grams, 0.001)
    }

    @Test fun excludesSameRecipeInAnotherMealAndAnotherCookingBatch() {
        val first = meal(origin = 0)
        val p = plan(listOf(first, meal(name = "Ужин", origin = 0)), listOf(meal(origin = 1)))
        val batch = PlanCookingDetails.batch(p, 0, first)
        assertEquals(1, batch.portions)
        assertEquals(100.0, batch.ingredients.single().grams, 0.001)
    }

    @Test fun nullOriginInLegacyPlanMeansCurrentDay() {
        val first = meal()
        val batch = PlanCookingDetails.batch(plan(listOf(first), listOf(first)), 1, first)
        assertEquals(1, batch.preparedOnDay)
        assertEquals(1, batch.portions)
    }

    @Test fun waterSumsOnlyLinkedPortionsAndSupportsLegacyNull() {
        val first = meal(origin = 0).copy(cookingWaterMl = 200.0)
        val reheat = meal(origin = 0).copy(cookingWaterMl = 150.0, timeKind = "reheat")
        val other = meal(name = "Ужин", origin = 0).copy(cookingWaterMl = 900.0)
        val batch = PlanCookingDetails.batch(plan(listOf(first, other), listOf(reheat)), 1, reheat)
        assertEquals(350.0, batch.cookingWaterMl, 0.001)
        assertEquals(0.0, PlanCookingDetails.batch(plan(listOf(meal())), 0, meal()).cookingWaterMl, 0.001)
    }
}
