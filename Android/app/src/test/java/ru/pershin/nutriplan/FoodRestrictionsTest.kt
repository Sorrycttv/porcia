package ru.pershin.nutriplan

import org.junit.Assert.*
import org.junit.Test

class FoodRestrictionsTest {
    @Test
    fun oldProfileAliasesRestoreSelectionsAndKeepOtherExclusions() {
        val (allergens, products) = FoodRestrictions.split(
            listOf("МОЛОКО; яйца\nорехи", "milk", "курица", "Рис", "рис")
        )
        assertEquals(setOf("milk", "eggs", "nuts"), allergens)
        assertEquals(listOf("курица", "рис"), products)
    }

    @Test
    fun typedAllergensAreNotLostOrDuplicatedWhenSaving() {
        assertEquals(listOf("milk", "soy", "курица"),
            FoodRestrictions.combine(setOf("milk"), "молоко, соя; курица"))
    }

    @Test
    fun clearingAllSelectionsRemovesPreviouslySavedRestrictions() {
        assertEquals(emptyList<String>(), FoodRestrictions.combine(emptySet(), " \n"))
    }
}
