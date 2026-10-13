package ru.pershin.nutriplan

import android.os.Bundle
import android.util.Patterns
import android.widget.Button
import android.widget.EditText
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import android.widget.TextView

import android.content.Intent
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

// Экран регистрации
class RegisterActivity : AppCompatActivity() {

    // Метод вызывается при открытии экрана
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_register)

        // отступы от системных панелей
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

        // Находим элементы по идентификаторам из XML.
        val emailInput = findViewById<EditText>(R.id.emailInput)
        val passwordInput = findViewById<EditText>(R.id.passwordInput)
        val repeatPasswordInput =
            findViewById<EditText>(R.id.repeatPasswordInput)

        val registerButton =
            findViewById<Button>(R.id.registerButton)



            val loginText = findViewById<TextView>(R.id.loginText)

// на экран входа
            loginText.setOnClickListener {
                startActivity(Intent(this, LoginActivity::class.java))
            }

// Регистрация
            registerButton.setOnClickListener {
                val email = emailInput.text.toString().trim()
                val password = passwordInput.text.toString()
                val repeatedPassword = repeatPasswordInput.text.toString()


                emailInput.error = null
                passwordInput.error = null
                repeatPasswordInput.error = null

                // Проверка данных
                when {
                    email.isEmpty() -> {
                        emailInput.error = "Введите электронную почту"
                        emailInput.requestFocus()
                    }

                    !Patterns.EMAIL_ADDRESS.matcher(email).matches() -> {
                        emailInput.error = "Некорректный адрес электронной почты"
                        emailInput.requestFocus()
                    }

                    password.length < 8 -> {
                        passwordInput.error =
                            "Пароль должен содержать не менее 8 символов"
                        passwordInput.requestFocus()
                    }

                    password != repeatedPassword -> {
                        repeatPasswordInput.error =
                            "Пароли не совпадают"
                        repeatPasswordInput.requestFocus()
                    }

                    else -> {
                        registerButton.isEnabled = false
                        registerButton.text = "Регистрация..."
                        val request = RegisterRequest(
                            email = email,
                            password = password
                        )
                        ApiClient.service.register(request).enqueue(

                            object : Callback<AuthResponse> {
                                override fun onResponse(
                                    call: Call<AuthResponse>,
                                    response: Response<AuthResponse>
                                ) {
                                    registerButton.isEnabled = true
                                    registerButton.text = "Зарегистрироваться"
                                    val authResponse = response.body()
                                    if (response.isSuccessful && authResponse != null) {
                                        val preferences = getSharedPreferences(
                                            "nutriplan_session",
                                            MODE_PRIVATE
                                        )
                                        preferences.edit()
                                            .putString(
                                                "access_token",
                                                authResponse.accessToken
                                            )
                                            .putString("email", email)
                                            .apply()

                                        Toast.makeText(
                                            this@RegisterActivity,
                                            "Регистрация выполнена",
                                            Toast.LENGTH_SHORT
                                        ).show()
                                        val profileScreen = Intent(
                                            this@RegisterActivity,
                                            ProfileActivity::class.java
                                        )


                                        startActivity(profileScreen)
                                        finish()

                                    } else {
                                        val message = when (response.code()) {
                                            409 -> "Этот email уже зарегистрирован"
                                            else -> "Ошибка регистрации: ${response.code()}"
                                        }

                                        Toast.makeText(
                                            this@RegisterActivity,
                                            message,
                                            Toast.LENGTH_LONG
                                        ).show()
                                    }
                                }

                                override fun onFailure(
                                    call: Call<AuthResponse>,
                                    error: Throwable
                                ) {
                                    registerButton.isEnabled = true
                                    registerButton.text = "Зарегистрироваться"

                                    Toast.makeText(
                                        this@RegisterActivity,
                                        "Нет связи с сервером",
                                        Toast.LENGTH_LONG
                                    ).show()
                                }
                            }
                        )
                    }
                }
            }
        }

}
