package ru.pershin.nutriplan

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import android.view.View
import android.widget.ProgressBar
import android.widget.Toast
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import android.content.Intent
import android.widget.Button
import android.widget.EditText

class LoginActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_login)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main)) { v, insets ->
            val systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom)
            insets
        }
        // Связываем код с элементами XML.
        val email = findViewById<EditText>(R.id.emailEditText)
        val password = findViewById<EditText>(R.id.passwordEditText)
        val login = findViewById<Button>(R.id.loginButton)
        val progress = findViewById<ProgressBar>(R.id.loginProgressBar)
        val preferences = getSharedPreferences(
            "nutriplan_session",
            MODE_PRIVATE
        )

        // Email можно хранить локально; пароль намеренно не сохраняется.
        email.setText(preferences.getString("email", ""))

// Открываем регистрацию.
        findViewById<Button>(R.id.registerButton).setOnClickListener {
            startActivity(Intent(this, RegisterActivity::class.java))
        }

// Проверяем поля перед отправкой на сервер.
        login.setOnClickListener {
            val emailText = email.text.toString().trim()
            val passwordText = password.text.toString()

            email.error = null
            password.error = null

            when {
                !android.util.Patterns.EMAIL_ADDRESS.matcher(emailText).matches() ->
                    email.error = "Введите корректную почту"

                passwordText.isBlank() ->
                    password.error = "Введите пароль"

                else -> {progress.visibility = View.VISIBLE
                    login.isEnabled = false

                    ApiClient.service.login(
                        RegisterRequest(emailText, passwordText)
                    ).enqueue(object : Callback<AuthResponse> {

                        override fun onResponse(
                            call: Call<AuthResponse>,
                            response: Response<AuthResponse>
                        ) {
                            progress.visibility = View.GONE
                            login.isEnabled = true

                            val token = response.body()?.accessToken

                            if (response.isSuccessful && token != null) {
                                // Сохраняем токен авторизации.
                                preferences.edit()
                                    .putString("access_token", token)
                                    .putString("email", emailText)
                                    .apply()

                                startActivity(Intent(this@LoginActivity, HomeActivity::class.java))
                                finish()
                            } else {
                                Toast.makeText(
                                    this@LoginActivity,
                                    "Неверная почта или пароль",
                                    Toast.LENGTH_SHORT
                                ).show()
                            }
                        }

                        override fun onFailure(call: Call<AuthResponse>, error: Throwable) {
                            progress.visibility = View.GONE
                            login.isEnabled = true

                            Toast.makeText(
                                this@LoginActivity,
                                "Нет связи с сервером",
                                Toast.LENGTH_SHORT
                            ).show()
                        }
                    })
                }
            }
        }
    }
}
