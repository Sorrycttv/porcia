package ru.pershin.nutriplan

object FridgeInputParser {
    private val separators = Regex("""[\n;]|(?<!\d),|,(?!\d)""")
    private val quantity = Regex(
        """(\d+(?:[.,]\d+)?)\s*(килограмм(?:а|ов)?|кг|грамм(?:а|ов)?|гр|г)(?![\p{L}])""",
        RegexOption.IGNORE_CASE
    )

    fun parse(text: String): Pair<List<PantryItemRequest>, List<String>> {
        val items = mutableListOf<PantryItemRequest>()
        val invalid = mutableListOf<String>()
        text.split(separators).map { it.trim() }.filter { it.isNotEmpty() }.forEach { row ->
            val matches = quantity.findAll(row).toList()
            if (matches.size != 1) {
                invalid += row
                return@forEach
            }
            val match = matches.single()
            val amount = match.groupValues[1].replace(',', '.').toDoubleOrNull()
            val unit = match.groupValues[2].lowercase()
            val product = row.removeRange(match.range).trim(' ', ':', '-', '–', '—')
            val grams = amount?.let {
                if (unit.startsWith("кг") || unit.startsWith("килограмм")) it * 1000 else it
            }
            if (grams == null || !grams.isFinite() || grams <= 0 || grams > 100000 ||
                product.isBlank() || product.length > 100 ||
                Regex("""[-−]\s*$""").containsMatchIn(row.substring(0, match.range.first))
            ) {
                invalid += row
            } else {
                items += PantryItemRequest(product, grams)
            }
        }
        if (items.isEmpty() && invalid.isEmpty() && text.isNotBlank()) invalid += text.trim()
        return items to invalid
    }

    fun formatGrams(grams: Double): String =
        java.math.BigDecimal.valueOf(grams).stripTrailingZeros().toPlainString().replace('.', ',')
}
