package ru.pershin.nutriplan

/** Uses the saved portions rather than multiplying one portion by a batch count. */
object PlanCookingDetails {
    data class Batch(val preparedOnDay: Int, val portions: Int, val ingredients: List<RecipeIngredient>, val cookingWaterMl: Double = 0.0)

    fun batch(plan: PlanResponse, dayIndex: Int, meal: PlanMeal): Batch {
        val origin = meal.preparedOnDay ?: dayIndex
        val portions = plan.days.flatMapIndexed { index, day ->
            day.meals.filter {
                it.meal == meal.meal && it.recipe == meal.recipe &&
                    (it.preparedOnDay ?: index) == origin
            }
        }
        // Older plans without ingredient snapshots can still display their instructions.
        val ingredients = portions.flatMap { it.ingredients.orEmpty() }
            .groupBy { it.product }.map { (product, values) ->
                RecipeIngredient(product, values.sumOf { it.grams })
            }
        return Batch(origin, portions.size, ingredients, portions.sumOf { it.cookingWaterMl ?: 0.0 })
    }
}
