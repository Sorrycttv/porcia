package ru.pershin.nutriplan

import java.security.MessageDigest

/** Both a new menu and a changed purchase quantity require checking purchases again. */
object ShoppingChecklist {
    fun identity(plan: PlanResponse): String? = plan.revision ?: plan.planId?.let { "legacy_$it" }

    fun key(plan: PlanResponse, items: List<ShoppingItem>, periodScope: String = "all"): String? {
        val identity = identity(plan) ?: return null
        val snapshot = items.sortedBy { it.product }.joinToString("\n") {
            "${it.product}\t${it.grams}\t${it.packagesToBuy}\t${it.packageGrams}\t${it.expectedLeftoverGrams}"
        }
        val hash = MessageDigest.getInstance("SHA-256").digest(snapshot.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        return "$identity:$periodScope:$hash"
    }
}
