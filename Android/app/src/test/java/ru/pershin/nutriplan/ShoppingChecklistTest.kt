package ru.pershin.nutriplan

import org.junit.Assert.*
import org.junit.Test

class ShoppingChecklistTest {
    private val plan = PlanResponse(revision = "menu-a", periodDays = 7, targetCalories = 2000.0,
        days = emptyList(), shoppingList = emptyList(), estimatedPeriodCost = 100, estimatedMonthlyCost = 400)
    private val rice = ShoppingItem("Рис", 300, 1, 500, 200)
    private val chicken = ShoppingItem("Куриное филе", 800, 2, 400, 0)

    @Test fun changedMenuOrQuantityDoesNotReuseCheckedPurchases() {
        val original = ShoppingChecklist.key(plan, listOf(rice))
        assertNotEquals(original, ShoppingChecklist.key(plan.copy(revision = "menu-b"), listOf(rice)))
        assertNotEquals(original, ShoppingChecklist.key(plan, listOf(rice.copy(grams = 350))))
    }

    @Test fun displayOrderDoesNotDiscardPurchases() {
        assertEquals(ShoppingChecklist.key(plan, listOf(rice, chicken)),
            ShoppingChecklist.key(plan, listOf(chicken, rice)))
        assertNull(ShoppingChecklist.key(plan.copy(revision = null), listOf(rice)))
    }

    @Test fun identicalShoppingForDifferentWeeksHasSeparateCheckmarks() {
        assertNotEquals(ShoppingChecklist.key(plan, listOf(rice), "1-7"),
            ShoppingChecklist.key(plan, listOf(rice), "8-14"))
    }
}
