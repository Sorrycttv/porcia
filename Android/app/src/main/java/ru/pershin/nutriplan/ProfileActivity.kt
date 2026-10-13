package ru.pershin.nutriplan

import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.Spinner
import android.widget.Toast
import android.widget.CheckBox
import android.widget.LinearLayout
import androidx.core.content.ContextCompat
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import android.content.Intent
import com.google.gson.Gson

// Экран заполнения параметров пользователя.
class ProfileActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_profile)
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

        // Находим элементы интерфейса.
        val sexSpinner = findViewById<Spinner>(R.id.sexSpinner)
        val activitySpinner =
            findViewById<Spinner>(R.id.activitySpinner)
        val goalSpinner = findViewById<Spinner>(R.id.goalSpinner)

        val ageInput = findViewById<EditText>(R.id.ageInput)
        val heightInput = findViewById<EditText>(R.id.heightInput)
        val weightInput = findViewById<EditText>(R.id.weightInput)
        val restrictionsInput = findViewById<EditText>(R.id.restrictionsInput)
        val allergenContainer = findViewById<LinearLayout>(R.id.allergenOptions)
        val allergenOptions = FoodRestrictions.labels.mapValues { (_, label) ->
            CheckBox(this).apply {
                text = label
                minHeight = (48 * resources.displayMetrics.density).toInt()
                setTextColor(ContextCompat.getColor(this@ProfileActivity, R.color.nutriplan_text))
                allergenContainer.addView(this)
            }
        }
        val preferredFoodsInput =
            findViewById<EditText>(R.id.preferredFoodsInput)
        val budgetInput = findViewById<EditText>(R.id.budgetInput)

        val saveButton =
            findViewById<Button>(R.id.saveProfileButton)

        // Варианты, которые видит пользователь.
        val sexNames = listOf(
            "Мужской",
            "Женский"
        )
        val activityNames = listOf(
            "Низкая",
            "Лёгкая",
            "Средняя",
            "Высокая"
        )
        val goalNames = listOf(
            "Снижение веса",
            "Поддержание веса",
            "Набор веса"
        )

        // Значения, которые ожидает Python API.
        val sexValues = listOf("male", "female")
        val activityValues =
            listOf("low", "light", "moderate", "high")
        val goalValues = listOf("lose", "maintain", "gain")

        // Одинаково заполняет форму из локального кэша или ответа сервера.
        fun showProfile(profile: ProfileRequest) {
            sexSpinner.setSelection(
                sexValues.indexOf(profile.sex).coerceAtLeast(0)
            )
            activitySpinner.setSelection(
                activityValues.indexOf(profile.activity).coerceAtLeast(0)
            )
            goalSpinner.setSelection(
                goalValues.indexOf(profile.goal).coerceAtLeast(0)
            )
            ageInput.setText(profile.age.toString())
            heightInput.setText(profile.heightCm.toString())
            weightInput.setText(profile.weightKg.toString())
            val (allergens, products) = FoodRestrictions.split(profile.restrictions)
            allergenOptions.forEach { (code, option) -> option.isChecked = code in allergens }
            restrictionsInput.setText(products.joinToString(", "))
            preferredFoodsInput.setText(profile.preferredFoods.joinToString(", "))
            budgetInput.setText(profile.monthlyBudget?.toString().orEmpty())
        }

        // Вспомогательная функция заполняет Spinner.
        fun setupSpinner(
            spinner: Spinner,
            values: List<String>
        ) {
            val adapter = ArrayAdapter(
                this,
                android.R.layout.simple_spinner_item,
                values
            )

            // Разметка раскрытого списка.
            adapter.setDropDownViewResource(
                android.R.layout.simple_spinner_dropdown_item
            )

            spinner.adapter = adapter
        }

        // Заполняем выпадающие списки.
        setupSpinner(sexSpinner, sexNames)
        setupSpinner(activitySpinner, activityNames)
        setupSpinner(goalSpinner, goalNames)

        // Читаем сохранённый после регистрации токен.
        val token = getSharedPreferences(
            "nutriplan_session",
            MODE_PRIVATE
        ).getString("access_token", null)

        // Без токена сервер не сможет определить пользователя.
        if (token == null) {
            Toast.makeText(
                this,
                "Сессия не найдена. Зарегистрируйтесь заново",
                Toast.LENGTH_LONG
            ).show()

            finish()
            return
        }

        // Сначала восстанавливаем профиль с телефона без ожидания сети.
        val profileCache = getSharedPreferences(
            "nutriplan_profile",
            MODE_PRIVATE
        )
        profileCache.getString("profile_json", null)?.let { json ->
            runCatching {
                Gson().fromJson(json, ProfileRequest::class.java)
            }.getOrNull()?.let(::showProfile)
        }

        // Загружаем сохранённые данные и подставляем их в форму.
        ApiClient.service.getProfile("Bearer $token").enqueue(
            object : Callback<ProfileResponse> {
                override fun onResponse(
                    call: Call<ProfileResponse>,
                    response: Response<ProfileResponse>
                ) {
                    val savedProfile = response.body()?.profile ?: return
                    val profile = savedProfile.copy(diet = "none")
                    if (savedProfile.diet != "none") {
                        ApiClient.service.saveProfile("Bearer $token", profile).enqueue(
                            object : Callback<StatusResponse> {
                                override fun onResponse(call: Call<StatusResponse>, response: Response<StatusResponse>) {
                                    if (!response.isSuccessful) {
                                        Toast.makeText(this@ProfileActivity, "Нажмите «Сохранить профиль», чтобы сбросить прежний тип питания", Toast.LENGTH_LONG).show()
                                    }
                                }
                                override fun onFailure(call: Call<StatusResponse>, error: Throwable) {
                                    Toast.makeText(this@ProfileActivity, "Не удалось сбросить прежний тип питания. Сохраните профиль при подключении к сети", Toast.LENGTH_LONG).show()
                                }
                            }
                        )
                    }
                    showProfile(profile)
                    profileCache.edit()
                        .putString("profile_json", Gson().toJson(profile))
                        .apply()
                }

                override fun onFailure(
                    call: Call<ProfileResponse>,
                    error: Throwable
                ) {
                    Toast.makeText(
                        this@ProfileActivity,
                        "Не удалось загрузить сохранённый профиль",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        )

        // Преобразует строку продуктов в список.
        // Можно вводить через запятую, точку с запятой или новую строку.
        fun parseProducts(text: String): List<String> {
            return text
                .split(",", ";", "\n")
                .map { product -> product.trim() }
                .filter { product -> product.isNotEmpty() }
        }

        saveButton.setOnClickListener {

            // Считываем и преобразуем числовые значения.
            val age = ageInput.text.toString().toIntOrNull()
            val height =
                heightInput.text.toString().replace(",", ".").toDoubleOrNull()
            val weight =
                weightInput.text.toString().replace(",", ".").toDoubleOrNull()

            val budgetText = budgetInput.text.toString().trim()
            val budget = if (budgetText.isEmpty()) {
                null
            } else {
                budgetText.replace(",", ".").toDoubleOrNull()
            }

            // Удаляем предыдущие ошибки.
            ageInput.error = null
            heightInput.error = null
            weightInput.error = null
            budgetInput.error = null

            // Проверяем допустимые значения.
            when {
                age == null || age !in 18..100 -> {
                    ageInput.error = "Укажите возраст от 18 до 100 лет"
                    ageInput.requestFocus()
                }

                height == null || height !in 120.0..230.0 -> {
                    heightInput.error = "Укажите рост от 120 до 230 см"
                    heightInput.requestFocus()
                }

                weight == null || weight !in 35.0..300.0 -> {
                    weightInput.error = "Укажите вес от 35 до 300 кг"
                    weightInput.requestFocus()
                }

                budgetText.isNotEmpty() &&
                        (budget == null || !budget.isFinite() || budget !in 1000.0..300000.0) -> {

                    budgetInput.error =
                        "Укажите бюджет от 1000 до 300000 рублей"
                    budgetInput.requestFocus()
                }

                else -> {
                    // Формируем объект для отправки на сервер.
                    val request = ProfileRequest(
                        sex = sexValues[sexSpinner.selectedItemPosition],
                        age = age,
                        heightCm = height,
                        weightKg = weight,
                        activity = activityValues[
                            activitySpinner.selectedItemPosition
                        ],
                        goal = goalValues[
                            goalSpinner.selectedItemPosition
                        ],
                        diet = "none",
                        restrictions = FoodRestrictions.combine(
                            allergenOptions.filterValues { it.isChecked }.keys,
                            restrictionsInput.text.toString()
                        ),
                        preferredFoods = parseProducts(
                            preferredFoodsInput.text.toString()
                        ),
                        targetCalories = null,
                        monthlyBudget = budget
                    )

                    // Защищаемся от повторных нажатий.
                    saveButton.isEnabled = false
                    saveButton.text = "Сохранение..."

                    // Отправляем профиль с токеном авторизации.
                    ApiClient.service.saveProfile(
                        authorization = "Bearer $token",
                        request = request
                    ).enqueue(object : Callback<StatusResponse> {

                        override fun onResponse(
                            call: Call<StatusResponse>,
                            response: Response<StatusResponse>
                        ) {
                            saveButton.isEnabled = true
                            saveButton.text = "Сохранить профиль"

                            if (response.isSuccessful) {
                                // Кэш ускоряет повторное открытие формы на этом телефоне.
                                profileCache.edit()
                                    .putString("profile_json", Gson().toJson(request))
                                    .apply()

                                Toast.makeText(
                                    this@ProfileActivity,
                                    "Профиль сохранён",

                                    Toast.LENGTH_SHORT
                                ).show()
                                // Создаём переход на главный экран.
                                val homeScreen = Intent(
                                    this@ProfileActivity,
                                    HomeActivity::class.java
                                )
                                homeScreen.flags =
                                    Intent.FLAG_ACTIVITY_NEW_TASK or
                                            Intent.FLAG_ACTIVITY_CLEAR_TASK
                                startActivity(homeScreen)
                            }
                            else {
                                val message = when (response.code()) {
                                    401 -> "Сессия истекла"
                                    400 -> "Проверьте введённые значения"
                                    else -> "Ошибка сервера: ${response.code()}"
                                }

                                Toast.makeText(
                                    this@ProfileActivity,
                                    message,
                                    Toast.LENGTH_LONG
                                ).show()
                            }
                        }

                        override fun onFailure(
                            call: Call<StatusResponse>,
                            error: Throwable
                        ) {
                            saveButton.isEnabled = true
                            saveButton.text = "Сохранить профиль"

                            Toast.makeText(
                                this@ProfileActivity,
                                "Нет связи с сервером",
                                Toast.LENGTH_LONG
                            ).show()
                        }
                    })
                }
            }
        }
    }
}
