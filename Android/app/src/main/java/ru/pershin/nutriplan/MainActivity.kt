package ru.pershin.nutriplan

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

// экран входа
class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)

        // Если сохранённый токен ещё действителен, повторный вход не требуется.
        restoreSession()

        val startButton = findViewById<Button>(R.id.startButton)
        startButton.setOnClickListener {
            val registerScreen = Intent(
                this,
                RegisterActivity::class.java
            )
            startActivity(registerScreen)
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

    private fun restoreSession() {
        val preferences = getSharedPreferences(
            "nutriplan_session",
            MODE_PRIVATE
        )
        val token = preferences.getString("access_token", null) ?: return

        ApiClient.service.getProfile("Bearer $token").enqueue(
            object : Callback<ProfileResponse> {
                override fun onResponse(
                    call: Call<ProfileResponse>,
                    response: Response<ProfileResponse>
                ) {
                    if (response.isSuccessful) {
                        val destination = if (response.body()?.profile == null) {
                            ProfileActivity::class.java
                        } else {
                            HomeActivity::class.java
                        }
                        startActivity(Intent(this@MainActivity, destination))
                        finish()
                    } else if (response.code() == 401) {
                        // Удаляем только недействительный токен.
                        preferences.edit().remove("access_token").apply()
                    }
                }

                override fun onFailure(
                    call: Call<ProfileResponse>,
                    error: Throwable
                ) {
                    // При отсутствии сети остаёмся на стартовом экране.
                }
            }
        )
    }
}
