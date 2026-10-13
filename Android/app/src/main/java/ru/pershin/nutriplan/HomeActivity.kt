package ru.pershin.nutriplan

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

// Главный экран
class HomeActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enableEdgeToEdge()
        setContentView(R.layout.activity_home)
        findViewById<Button>(R.id.profileButton).setOnClickListener {
            startActivity(Intent(this, ProfileActivity::class.java))
        }
        findViewById<Button>(R.id.planButton).setOnClickListener {
            startActivity(Intent(this, PlanActivity::class.java))
        }
        findViewById<Button>(R.id.coachButton).setOnClickListener {
            startActivity(Intent(this, activity_acriv_coach::class.java))
        }
        findViewById<Button>(R.id.fridgeButton).setOnClickListener {
            startActivity(Intent(this, FridgeActivity::class.java))
        }
        findViewById<Button>(R.id.storePricesButton).setOnClickListener {
            startActivity(Intent(this, StorePricesActivity::class.java))
        }
        // Книга блюд открывает проверенный каталог без обязательного запроса.
        findViewById<Button>(R.id.recipesButton).setOnClickListener {
            startActivity(
                Intent(this, RecipeSearchActivity::class.java)
                    .putExtra("catalog_mode", true)
            )
        }
        // Свободный поиск проверенного рецепта по названию или ингредиенту.
        findViewById<Button>(R.id.askRecipeButton).setOnClickListener {
            startActivity(Intent(this, RecipeSearchActivity::class.java))
        }
        ViewCompat.setOnApplyWindowInsetsListener(
            findViewById(R.id.main)
        ) { view, insets ->
            val systemBars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars()
            )
            view.setPadding(
                systemBars.left,
                systemBars.top,
                systemBars.right,
                systemBars.bottom
            )

            insets
        }
    }
}
