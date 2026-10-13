package ru.pershin.nutriplan

import java.util.Locale

/** Stable API codes for the seven restriction groups supported by the server. */
object FoodRestrictions {
    val labels = linkedMapOf(
        "milk" to "Молочные продукты",
        "eggs" to "Яйца",
        "fish" to "Рыба",
        "nuts" to "Орехи и арахис",
        "soy" to "Соя",
        "sesame" to "Кунжут",
        "gluten" to "Глютен"
    )
    private val aliases = mapOf(
        "молоко" to "milk", "молочные продукты" to "milk", "молочный белок" to "milk",
        "яйца" to "eggs", "яйцо" to "eggs", "яиц" to "eggs",
        "рыба" to "fish", "орехи" to "nuts", "арахис" to "nuts",
        "соя" to "soy", "кунжут" to "sesame", "глютен" to "gluten"
    )

    fun split(values: List<String>): Pair<Set<String>, List<String>> {
        val allergens = linkedSetOf<String>()
        val products = linkedSetOf<String>()
        values.flatMap { it.split(',', ';', '\n') }.forEach { value ->
            val clean = value.trim().lowercase(Locale.ROOT).replace('ё', 'е')
            val code = aliases[clean] ?: clean
            if (code in labels) allergens += code else if (clean.isNotEmpty()) products += clean
        }
        return allergens to products.toList()
    }

    fun combine(selected: Set<String>, text: String): List<String> {
        val (typedAllergens, products) = split(listOf(text))
        return labels.keys.filter { it in selected || it in typedAllergens } + products
    }
}
