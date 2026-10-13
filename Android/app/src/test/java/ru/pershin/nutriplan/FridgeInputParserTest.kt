package ru.pershin.nutriplan

import org.junit.Assert.*
import org.junit.Test

class FridgeInputParserTest {
    @Test
    fun decimalCommaIsKeptWhenProductsAreSeparatedByCommas() {
        val (items, invalid) = FridgeInputParser.parse("Рис 0,5 кг, курица 250 г; 1,25 кг картофеля")
        assertTrue(invalid.isEmpty())
        assertEquals(listOf("Рис", "курица", "картофеля"), items.map { it.product })
        assertEquals(listOf(500.0, 250.0, 1250.0), items.map { it.grams })
    }

    @Test
    fun completeUnitNamesDoNotBecomePartOfTheProduct() {
        val (items, invalid) = FridgeInputParser.parse("Рис: 80 граммов\nМолоко — 0.75 килограмма")
        assertTrue(invalid.isEmpty())
        assertEquals(listOf("Рис", "Молоко"), items.map { it.product })
        assertEquals(listOf(80.0, 750.0), items.map { it.grams })
    }

    @Test
    fun emptyInputCanClearStockButSeparatorsAloneCannot() {
        assertEquals(emptyList<PantryItemRequest>() to emptyList<String>(), FridgeInputParser.parse(" \n "))
        assertTrue(FridgeInputParser.parse(";,,").second.isNotEmpty())
    }

    @Test
    fun invalidQuantitiesAreReportedInsteadOfSilentlySavingPartOfARow() {
        listOf("Рис", "0 г риса", "-5 г риса", "Рис -5 г", "Рис 101 кг", "Рис 50 г 20 г").forEach {
            val (items, invalid) = FridgeInputParser.parse(it)
            assertTrue(it, items.isEmpty())
            assertEquals(listOf(it), invalid)
        }
    }

    @Test
    fun fractionalGramsSurviveDisplayAndEditing() {
        val formatted = FridgeInputParser.formatGrams(0.4)
        assertEquals("0,4", formatted)
        val (items, invalid) = FridgeInputParser.parse("Соль $formatted г")
        assertTrue(invalid.isEmpty())
        assertEquals(0.4, items.single().grams, 0.000001)
    }
}
