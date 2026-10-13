package ru.pershin.nutriplan

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.LinearLayout
import android.widget.ScrollView
import androidx.activity.enableEdgeToEdge
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.appcompat.app.AppCompatActivity
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

// Один экран обслуживает каталог блюд и точный поиск рецепта.
class RecipeSearchActivity : AppCompatActivity() {
    private var activeCall: Call<RecipesResponse>? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_recipe_search)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        val title = findViewById<TextView>(R.id.recipeScreenTitle)
        val input = findViewById<EditText>(R.id.dishInput)
        val button = findViewById<Button>(R.id.searchButton)
        val progress = findViewById<ProgressBar>(R.id.searchProgressBar)
        val result = findViewById<TextView>(R.id.resultText)

        // Null означает загрузку всей книги блюд, строка — фильтрацию каталога.
        fun loadRecipes(query: String?) {
            findViewById<LinearLayout>(R.id.recipeCardsContainer).removeAllViews()
            val token = getSharedPreferences(
                "nutriplan_session",
                MODE_PRIVATE
            ).getString("access_token", null)

            if (token == null) {
                result.text = "Сессия истекла. Выполните вход заново."
                return
            }

            progress.visibility = View.VISIBLE
            button.isEnabled = false

            activeCall?.cancel()
            activeCall = ApiClient.service.getRecipes("Bearer $token", query)
            activeCall!!.enqueue(
                object : Callback<RecipesResponse> {
                    override fun onResponse(
                        call: Call<RecipesResponse>,
                        response: Response<RecipesResponse>
                    ) {
                        if (isDestroyed || isFinishing || call.isCanceled) return
                        progress.visibility = View.GONE
                        button.isEnabled = true

                        if (!response.isSuccessful) {
                            result.text = "Не удалось загрузить рецепты. Код: ${response.code()}"
                            return
                        }
                        renderRecipeCards(response.body()?.recipes.orEmpty())
                    }

                    override fun onFailure(
                        call: Call<RecipesResponse>,
                        error: Throwable
                    ) {
                        if (isDestroyed || isFinishing || call.isCanceled) return
                        progress.visibility = View.GONE
                        button.isEnabled = true
                        result.text = "Не удалось загрузить каталог: ${error.localizedMessage}"
                    }
                }
            )
        }

        button.setOnClickListener {
            val query = input.text.toString().trim()
            if (query.length < 2) {
                input.error = "Введите минимум 2 символа"
                return@setOnClickListener
            }
            loadRecipes(query)
        }

        if (intent.getBooleanExtra("catalog_mode", false)) {
            title.text = "Книга блюд"
            input.hint = "Введите название блюда из каталога"
            loadRecipes(null)
        }
    }

    private fun renderRecipeCards(recipes: List<RecipeItem>) {
        val container = findViewById<LinearLayout>(R.id.recipeCardsContainer)
        container.removeAllViews()
        findViewById<TextView>(R.id.resultText).text = if (recipes.isEmpty()) "Подходящих блюд не найдено." else "Блюд доступно: ${recipes.size} · с учётом твоего профиля"
        recipes.forEach { recipe ->
            val card = PorciaUi.card(this)
            card.addView(PorciaUi.text(this, recipe.name, 19f, bold = true))
            card.addView(PorciaUi.text(this, "${recipe.calories} ккал · ${recipe.preparationMinutes} мин", 14f, muted = true))
            card.addView(PorciaUi.text(this, recipe.ingredients.take(3).joinToString(" · ") { it.product }, 14f, muted = true))
            card.addView(PorciaUi.action(this, "Открыть рецепт").apply {
                contentDescription = "Открыть рецепт: ${recipe.name}"
                setOnClickListener {
                    val text = PorciaUi.text(this@RecipeSearchActivity, formatRecipe(recipe)).apply {
                        setPadding(PorciaUi.dp(context, 20), PorciaUi.dp(context, 12), PorciaUi.dp(context, 20), PorciaUi.dp(context, 20))
                        autoLinkMask = android.text.util.Linkify.WEB_URLS
                        movementMethod = android.text.method.LinkMovementMethod.getInstance()
                    }
                    androidx.appcompat.app.AlertDialog.Builder(this@RecipeSearchActivity)
                        .setTitle(recipe.name).setView(ScrollView(this@RecipeSearchActivity).apply { addView(text) })
                        .setPositiveButton("Понятно", null).show()
                }
            })
            container.addView(card)
        }
    }

    override fun onDestroy() {
        activeCall?.cancel()
        super.onDestroy()
    }

    private fun formatRecipe(recipe: RecipeItem): String {
        val ingredients = recipe.ingredients.joinToString("\n") {
            "• ${it.product}: ${FridgeInputParser.formatGrams(it.grams)} г"
        }
        return buildString {
            appendLine("Вес ингредиентов: ${recipe.portionWeightGrams} г")
            appendLine("Время: ${recipe.preparationMinutes} мин")
            appendLine()
            appendLine("Калорийность: ${recipe.calories} ккал (оценка)")
            appendLine("Источник: ${recipe.nutritionSource ?: "Источник расчёта не указан"}")
            appendLine("Вес круп указан до варки; итоговый вес блюда может отличаться.")
            appendLine()
            appendLine("Ингредиенты:")
            appendLine(ingredients)
            appendLine()
            appendLine("Как приготовить:")
            append(recipe.instructions)
            recipe.cookingWaterMl?.takeIf { it > 0 }?.let {
                append("\n\nВода для основы: ${FridgeInputParser.formatGrams(it)} мл.")
            }
            recipe.recipeSourceUrl?.let {
                append("\n\nОснова рецепта: $it")
                recipe.recipeAdaptationNote?.takeIf { it.isNotBlank() }?.let { note -> append("\n$note") }
            }
        }
    }
}
