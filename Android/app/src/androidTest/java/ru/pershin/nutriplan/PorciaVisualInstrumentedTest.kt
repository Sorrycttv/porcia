package ru.pershin.nutriplan

import android.graphics.Bitmap
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatDelegate
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Rendering fixtures stay in the test APK; they never populate the server. */
@RunWith(AndroidJUnit4::class)
class PorciaVisualInstrumentedTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()

    private fun capture(name: String) {
        instrumentation.waitForIdleSync()
        Thread.sleep(300)
        val bitmap = instrumentation.uiAutomation.takeScreenshot()
        instrumentation.targetContext.openFileOutput("porcia-$name.png", 0).use {
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)
        }
        bitmap.recycle()
    }

    @Test fun nativeScreensRenderInBothThemesAndRecipeActionsRemainLocal() {
        try {
            for ((label, mode) in listOf("light" to AppCompatDelegate.MODE_NIGHT_NO, "dark" to AppCompatDelegate.MODE_NIGHT_YES)) {
                instrumentation.runOnMainSync { AppCompatDelegate.setDefaultNightMode(mode) }
                ActivityScenario.launch(HomeActivity::class.java).use { scenario ->
                    scenario.onActivity { assertEquals("Мой план", it.findViewById<Button>(R.id.planButton).text.toString()) }
                    capture("$label-home")
                }
                ActivityScenario.launch(LoginActivity::class.java).use { capture("$label-login") }
                ActivityScenario.launch(ProfileActivity::class.java).use { capture("$label-profile") }
                ActivityScenario.launch(PlanActivity::class.java).use { scenario ->
                    capture("$label-settings")
                    scenario.onActivity { activity ->
                        val meals = listOf(
                            PlanMeal("Завтрак", "Овсянка с бананом", 250, 480, 95, 10, "cook",
                                ingredients = listOf(RecipeIngredient("Овсяные хлопья", 70.0), RecipeIngredient("Молоко", 100.0), RecipeIngredient("Банан", 60.0), RecipeIngredient("Арахисовая паста", 20.0)), instructions = "1. Приготовьте кашу на молоке.\n2. Добавьте банан и арахисовую пасту."),
                            PlanMeal("Обед", "Паста с лососем и брокколи", 450, 720, 210, 30, "cook", batchServingsToPrepare = 2,
                                ingredients = listOf(RecipeIngredient("Лосось", 100.0), RecipeIngredient("Макароны цельнозерновые", 80.0), RecipeIngredient("Брокколи", 150.0), RecipeIngredient("Помидоры", 100.0), RecipeIngredient("Оливковое масло", 20.0)), instructions = "1. Отварите макароны и брокколи.\n2. Приготовьте рыбу с помидорами и маслом.\n3. Соедините ингредиенты."),
                            PlanMeal("Ужин", "Гречка с курицей", 400, 600, 160, 4, "reheat", preparedOnDay = 0,
                                ingredients = listOf(RecipeIngredient("Курица", 150.0), RecipeIngredient("Гречка", 70.0), RecipeIngredient("Овощи", 170.0), RecipeIngredient("Оливковое масло", 10.0))),
                            PlanMeal("Перекус", "Йогурт с яблоком", 250, 240, 70, 5, "cook",
                                ingredients = listOf(RecipeIngredient("Йогурт", 200.0), RecipeIngredient("Яблоко", 50.0)))
                        )
                        val fixture = PlanResponse(revision = "visual-fixture", periodDays = 1, targetCalories = 2040.0,
                            days = listOf(PlanDay("2026-10-11", meals, 535)), shoppingList = emptyList(),
                            estimatedPeriodCost = 535, estimatedMonthlyCost = 16050)
                        PlanActivity::class.java.getDeclaredMethod("showPlan", PlanResponse::class.java).apply { isAccessible = true }.invoke(activity, fixture)
                        assertEquals(View.GONE, activity.findViewById<View>(R.id.planSettingsContainer).visibility)
                        val details = activity.findViewById<LinearLayout>(R.id.planDetailsContainer)
                        assertTrue(details.childCount > 0)
                    }
                    capture("$label-plan")
                }
                ActivityScenario.launch(RecipeSearchActivity::class.java).use { scenario ->
                    scenario.onActivity { activity ->
                        val recipes = listOf(RecipeItem("Паста с лососем и брокколи", 560,
                            listOf(RecipeIngredient("Лосось", 75.0), RecipeIngredient("Макароны цельнозерновые", 62.5),
                                RecipeIngredient("Брокколи", 150.0), RecipeIngredient("Помидоры", 100.0), RecipeIngredient("Оливковое масло", 12.5)),
                            30, "1. Отварите макароны и брокколи.\n2. Приготовьте рыбу с помидорами и маслом.\n3. Соедините ингредиенты.", 400,
                            nutritionSource = "Демонстрационные данные UI-теста"))
                        assertEquals(400.0, recipes[0].ingredients.sumOf { it.grams }, 0.001)
                        RecipeSearchActivity::class.java.getDeclaredMethod("renderRecipeCards", List::class.java).apply { isAccessible = true }.invoke(activity, recipes)
                        assertTrue(activity.findViewById<TextView>(R.id.resultText).text.contains("1"))
                    }
                    capture("$label-catalogue")
                    scenario.onActivity { activity ->
                        val card = activity.findViewById<LinearLayout>(R.id.recipeCardsContainer).getChildAt(0) as LinearLayout
                        (card.getChildAt(card.childCount - 1) as Button).performClick()
                    }
                    capture("$label-recipe")
                }
            }
        } finally {
            instrumentation.runOnMainSync { AppCompatDelegate.setDefaultNightMode(AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM) }
        }
    }
}
