package ru.pershin.nutriplan

import android.os.Bundle
import android.content.Intent
import android.view.View
import android.widget.*
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.ViewModelProvider
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class PlanActivity : AppCompatActivity() {

    private lateinit var periodSpinner: Spinner
    private lateinit var modeSpinner: Spinner
    private lateinit var desiredInput: EditText
    private lateinit var wishInput: EditText
    private lateinit var wishButton: Button
    private lateinit var wishStatus: TextView
    private lateinit var surpriseCheckBox: CheckBox
    private lateinit var useFridgeCheckBox: CheckBox
    private lateinit var generateButton: Button
    private lateinit var resetButton: Button
    private lateinit var progress: ProgressBar
    private lateinit var result: TextView
    private lateinit var details: LinearLayout
    private lateinit var settingsPanel: LinearLayout
    private lateinit var settingsToggle: Button

    private val periods = listOf(1, 7)
    private val modes = listOf("variety", "balanced", "batch")
    private val replaceButtons = mutableListOf<Button>()
    private val pendingCalls = mutableSetOf<Call<*>>()
    private lateinit var operation: PlanOperationState
    private var awaitingMutation = false
    private var busy = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_plan)
        operation = ViewModelProvider(this)[PlanOperationState::class.java]

        periodSpinner = findViewById(R.id.periodSpinner)
        modeSpinner = findViewById(R.id.cookingModeSpinner)
        desiredInput = findViewById(R.id.desiredIngredientsInput)
        wishInput = findViewById(R.id.planWishInput)
        wishButton = findViewById(R.id.applyPlanWishButton)
        wishStatus = findViewById(R.id.planWishStatus)
        wishButton.setOnClickListener { applyWish() }
        surpriseCheckBox = findViewById(R.id.surpriseCheckBox)
        useFridgeCheckBox = findViewById(R.id.useFridgeCheckBox)
        generateButton = findViewById(R.id.generatePlanButton)
        resetButton = findViewById(R.id.resetPlanButton)
        progress = findViewById(R.id.planProgressBar)
        result = findViewById(R.id.planResultText)
        details = findViewById(R.id.planDetailsContainer)
        settingsPanel = findViewById(R.id.planSettingsContainer)
        settingsToggle = findViewById(R.id.planSettingsToggle)
        settingsToggle.setOnClickListener {
            settingsPanel.visibility = if (settingsPanel.visibility == View.VISIBLE) View.GONE else View.VISIBLE
            settingsToggle.text = if (settingsPanel.visibility == View.VISIBLE) "Скрыть настройки" else "Настроить меню"
        }

        // Подписи, которые видит пользователь.
        periodSpinner.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            listOf("1 день", "7 дней")
        )
        periodSpinner.setSelection(periods.indexOf(7))

        modeSpinner.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            listOf(
                "Каждый день",
                "Готовка с запасом на 2 дня",
                "Готовка с запасом на 2–3 дня"
            )
        )

        generateButton.setOnClickListener {
            generatePlan()
        }

        resetButton.setOnClickListener {
            clearPlan()
        }

        ViewCompat.setOnApplyWindowInsetsListener(
            findViewById(R.id.main)
        ) { view, insets ->
            val bars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars()
            )
            view.setPadding(
                bars.left,
                bars.top,
                bars.right,
                bars.bottom
            )
            insets
        }

        operation.pending.observe(this) { pending ->
            if (pending && pendingCalls.isEmpty()) {
                awaitingMutation = true
                showLoading(true)
                result.text = "Ожидаем завершения изменения меню…"
            } else if (!pending && awaitingMutation) {
                awaitingMutation = false
                loadCurrentPlan()
            }
        }
        // A retained mutation may still be selecting a recipe on the server.
        if (operation.pending.value == true) {
            awaitingMutation = true
            showLoading(true)
            result.text = "Ожидаем завершения изменения меню…"
        } else loadCurrentPlan()
    }

    private fun applyWish() {
        if (busy) return
        val token = getToken() ?: return
        val wish = wishInput.text.toString().trim()
        if (wish.length !in 3..500) {
            wishInput.error = "Опишите пожелание: от 3 до 500 символов"
            return
        }
        wishInput.error = null
        showLoading(true)
        wishStatus.text = "ИИ разбирает пожелание…"
        ApiClient.service.interpretPreferences("Bearer " + token, PreferenceRequest(wish))
            .enqueueTracked(object : Callback<PreferenceResponse> {
                override fun onResponse(call: Call<PreferenceResponse>, response: Response<PreferenceResponse>) {
                    showLoading(false)
                    val data = response.body()
                    val preferences = data?.preferences
                    if (!response.isSuccessful || data == null || !data.available || preferences == null) {
                        wishStatus.text = data?.message ?: "Не удалось применить пожелание. Выберите параметры вручную."
                        return
                    }
                    val periodIndex = periods.indexOf(preferences.days)
                    val modeIndex = modes.indexOf(preferences.cookingMode)
                    if (periodIndex >= 0) periodSpinner.setSelection(periodIndex)
                    if (modeIndex >= 0) modeSpinner.setSelection(modeIndex)
                    if (preferences.desiredIngredients.isNotEmpty()) {
                        val existing = desiredInput.text.toString().split(',', ';', '\n')
                            .map { it.trim() }.filter { it.isNotEmpty() }
                        desiredInput.setText((existing + preferences.desiredIngredients).distinct().joinToString(", "))
                    }
                    wishStatus.text = data.message + if (preferences.unhandledRequests.isEmpty()) "" else
                        "\nНе применено: " + preferences.unhandledRequests.joinToString("; ") +
                        ". Бюджет и исключения продуктов задаются в профиле."
                }
                override fun onFailure(call: Call<PreferenceResponse>, error: Throwable) {
                    showLoading(false)
                    wishStatus.text = "Не удалось дождаться ответа. Выберите параметры вручную."
                }
            })
    }

    private fun generatePlan() {
        if (busy) return
        val token = getToken() ?: return

        val desiredProducts = desiredInput.text.toString()
            .split(",", ";", "\n")
            .map { it.trim() }
            .filter { it.isNotEmpty() }

        val request = PlanRequest(
            days = periods[periodSpinner.selectedItemPosition],
            pantry = emptyList(),
            desiredIngredients = desiredProducts,
            menuWish = wishInput.text.toString().trim().take(500),
            surpriseMe = surpriseCheckBox.isChecked,
            cookingMode = modes[modeSpinner.selectedItemPosition]
        )

        showLoading(true)

        if (!useFridgeCheckBox.isChecked) {
            submitPlan(token, request)
            return
        }
        ApiClient.service.getFridge("Bearer $token").enqueueTracked(object : Callback<FridgeResponse> {
            override fun onResponse(call: Call<FridgeResponse>, response: Response<FridgeResponse>) {
                val fridge = response.body()
                if (!response.isSuccessful || fridge == null) {
                    showLoading(false)
                    result.text = "Не удалось загрузить холодильник. Рацион не изменён. Код: ${response.code()}"
                    return
                }
                submitPlan(token, request.copy(pantry = fridge.items))
            }

            override fun onFailure(call: Call<FridgeResponse>, error: Throwable) {
                showLoading(false)
                result.text = "Не удалось загрузить холодильник. Проверьте подключение и повторите."
            }
        })
    }

    private fun submitPlan(token: String, request: PlanRequest) {
        result.text = "Подбираем блюда с ИИ и рассчитываем рацион…"
        ApiClient.service.generatePlan(
            "Bearer $token",
            request
        ).enqueueMutation(object : Callback<PlanResponse> {

            override fun onResponse(
                call: Call<PlanResponse>,
                response: Response<PlanResponse>
            ) {
                showLoading(false)
                val plan = response.body()

                if (response.isSuccessful && plan != null) {
                    showPlan(plan)
                } else {
                    val detail = if (response.code() == 400) runCatching {
                        com.google.gson.JsonParser.parseString(response.errorBody()?.string().orEmpty())
                            .asJsonObject.get("detail")?.asString
                    }.getOrNull() else null
                    result.text = detail?.let { "Не удалось сформировать рацион.\n$it" }
                        ?: "Не удалось сформировать рацион. Код: ${response.code()}"
                }
            }

            override fun onFailure(
                call: Call<PlanResponse>,
                error: Throwable
            ) {
                showLoading(false)
                result.text = "Ошибка подключения: ${error.localizedMessage}"
            }
        })
    }

    private fun loadCurrentPlan() {
        val token = getToken() ?: return
        showLoading(true)

        ApiClient.service.getCurrentPlan(
            "Bearer $token"
        ).enqueueTracked(object : Callback<CurrentPlanResponse> {

            override fun onResponse(
                call: Call<CurrentPlanResponse>,
                response: Response<CurrentPlanResponse>
            ) {
                showLoading(false)

                if (!response.isSuccessful) {
                    result.text = "Не удалось загрузить план. Код: ${response.code()}"
                    return
                }
                val plan = response.body()?.plan
                if (plan != null) {
                    showPlan(plan)
                } else {
                    result.text = "Сохранённого плана пока нет."
                }
            }

            override fun onFailure(
                call: Call<CurrentPlanResponse>,
                error: Throwable
            ) {
                showLoading(false)
                result.text = "Не удалось загрузить сохранённый план."
            }
        })
    }

    private fun clearPlan() {
        if (busy) return
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Сбросить рацион?")
            .setMessage("Сохранённое меню будет удалено. Продукты в холодильнике сохранятся.")
            .setPositiveButton("Сбросить") { _, _ -> if (!busy) deleteCurrentPlan() }
            .setNegativeButton("Отмена", null).show()
    }

    private fun deleteCurrentPlan() {
        val token = getToken() ?: return
        showLoading(true)

        ApiClient.service.clearCurrentPlan(
            "Bearer $token"
        ).enqueueMutation(object : Callback<StatusResponse> {

            override fun onResponse(
                call: Call<StatusResponse>,
                response: Response<StatusResponse>
            ) {
                showLoading(false)
                if (!response.isSuccessful) {
                    result.text = "Не удалось сбросить план. Код: ${response.code()}"
                    return
                }
                details.removeAllViews()
                replaceButtons.clear()
                result.text = "План сброшен. Можно сформировать новый."
                settingsPanel.visibility = View.VISIBLE
                settingsToggle.text = "Скрыть настройки"
                resetButton.visibility = View.GONE
            }

            override fun onFailure(
                call: Call<StatusResponse>,
                error: Throwable
            ) {
                showLoading(false)
                result.text = "Не удалось сбросить план."
            }
        })
    }

    // Преобразует ответ сервера в понятный пользователю текст.
    private fun showPlan(plan: PlanResponse) {
        settingsPanel.visibility = View.GONE
        settingsToggle.text = "Изменить меню"
        // Старые планы доступны для просмотра; новый план создаётся на день или неделю.
        val periodIndex = periods.indexOf(plan.periodDays)
        periodSpinner.setSelection(if (periodIndex >= 0) periodIndex else periods.indexOf(7))

        modes.indexOf(plan.cookingMode).takeIf { it >= 0 }?.let {
            modeSpinner.setSelection(it)
        }
        details.removeAllViews()
        replaceButtons.clear()
        val mealNames = mapOf(
            "breakfast" to "Завтрак",
            "lunch" to "Обед",
            "dinner" to "Ужин",
            "snack" to "Перекус"
        )

        val aiMessage = when (plan.aiSelection?.status) {
            "applied" -> "ИИ участвовал в выборе блюд; сервер проверил меню и рассчитал порции."
            "unavailable" -> "ИИ не ответил. Меню подобрано по правилам приложения."
            "invalid_response" -> "Ответ ИИ не прошёл проверку. Меню подобрано по правилам приложения."
            "not_applied" -> "Для соблюдения условий использован подбор по правилам приложения."
            else -> "Меню подобрано по правилам приложения."
        }

        result.text =
            "Период плана: ${plan.periodDays} дн.\n" +
                    "Цель: ${plan.targetCalories.toInt()} ккал в день\n" +
                    "Примерная стоимость рациона: ${plan.estimatedPeriodCost} ₽" +
                    "\n$aiMessage" +
                    (if (periodIndex < 0) "\n\nЭто ранее сохранённый план. Новый рацион можно сформировать на 1 или 7 дней." else "") +
                    plan.warnings.orEmpty().joinToString(separator = "\n", prefix = if (plan.warnings.isNullOrEmpty()) "" else "\n\n")

        plan.days.chunked(7).forEachIndexed { weekIndex, days ->
            val start = weekIndex * 7 + 1
            val title = when (plan.periodDays) {
                1 -> "Рацион на день"
                7 -> "Рацион на неделю"
                else -> "Неделя ${weekIndex + 1}: дни $start–${start + days.size - 1}"
            }
            val week = expandable(details, title, weekIndex == 0)
            days.forEachIndexed { offset, day ->
                val body = expandable(week,
                    "День ${start + offset} · ${day.date} · ≈ ${day.estimatedCost} ₽",
                    weekIndex == 0 && offset == 0)
                body.addView(PorciaUi.badge(this, "${day.meals.sumOf { it.calories }} ккал · ${day.meals.size} приёма пищи"))
                day.meals.forEach { meal ->
                    val name = mealNames[meal.meal] ?: meal.meal
                    val card = PorciaUi.card(this)
                    card.addView(PorciaUi.text(this, "•  $name", 13f, muted = true, bold = true))
                    card.addView(PorciaUi.text(this, meal.recipe, 19f, bold = true))
                    card.addView(PorciaUi.text(this, "${meal.calories} ккал · ${meal.displayMinutes} мин · ≈ ${meal.estimatedCost} ₽ по оценке", 14f, muted = true))
                    val action = when {
                        meal.timeKind == "reheat" -> "Разогреваем" + (meal.preparedOnDay?.let { " · готовка в день ${it + 1}" } ?: "")
                        meal.batchServingsToPrepare > 1 -> "Готовим ${meal.batchServingsToPrepare} порции с запасом"
                        else -> "Готовим к подаче"
                    }
                    card.addView(PorciaUi.badge(this, action))
                    val actions = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
                    actions.addView(PorciaUi.action(this, "Рецепт").apply {
                        contentDescription = "Рецепт: ${meal.recipe}"
                        layoutParams = LinearLayout.LayoutParams(0, -2, 1f).apply { marginEnd = PorciaUi.dp(this@PlanActivity, 8) }
                        setOnClickListener { showCookingDetails(plan, start + offset - 1, meal) }
                    })
                    if (plan.revision != null && plan.periodDays in periods) {
                        val button = PorciaUi.action(this, "Заменить").apply {
                            contentDescription = "Заменить: $name"
                            layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
                            setOnClickListener {
                                if (!busy) chooseReplacement(plan, start + offset - 1, name)
                            }
                        }
                        replaceButtons.add(button)
                        actions.addView(button)
                    }
                    card.addView(actions)
                    body.addView(card)
                }
            }
        }
        val shopping = expandable(details, "Список покупок", false)
        val pantryUsed = plan.pantryUsed.orEmpty()
        if (pantryUsed.isNotEmpty()) {
            shopping.addView(planText("Учтено из холодильника:\n" +
                pantryUsed.joinToString("\n") {
                    "• ${it.product}: ${FridgeInputParser.formatGrams(it.grams)} г"
                } +
                "\n\nЭти количества вычтены из закупки. Запас в холодильнике не списывается автоматически."))
        }
        val weeks = plan.weeklyShopping.orEmpty()
        val selector = Spinner(this)
        selector.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item,
            listOf("Весь период") + weeks.map { "Дни ${it.startDay}–${it.endDay}" })
        selector.visibility = if (weeks.size > 1) View.VISIBLE else View.GONE
        shopping.addView(selector)
        shopping.addView(planText("Отмечайте купленные продукты. Отметки сохраняются на этом устройстве для текущей версии меню; после замены или генерации меню их нужно проверить заново. Они не пополняют холодильник автоматически."))
        val shoppingItems = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        shopping.addView(shoppingItems)
        val findProductsButton = PorciaUi.action(this, "Найти товары с ИИ", primary = true).apply {
            text = "Найти товары с ИИ"
            isAllCaps = false
            setOnClickListener {
                val position = selector.selectedItemPosition
                val weekIndex = if (position == 0) 0 else position - 1
                startActivity(Intent(this@PlanActivity, StorePricesActivity::class.java)
                    .putExtra("week_index", weekIndex))
            }
        }
        shopping.addView(findProductsButton)
        shopping.addView(PorciaUi.action(this, "Магазины рядом").apply {
            text = "Где купить продукты: карта и маршрут"
            isAllCaps = false
            setOnClickListener {
                val position = selector.selectedItemPosition
                startActivity(Intent(this@PlanActivity, StoreMapActivity::class.java)
                    .putExtra("week_index", if (position == 0) 0 else position - 1))
            }
        })
        shopping.addView(planText("Вес упаковки ориентировочный: сверьте его в магазине." +
            if (weeks.size > 1) " Недельные списки рассчитаны отдельно и не переносят остатки купленных упаковок между неделями." else ""))
        selector.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val items = if (position == 0) plan.shoppingList else weeks[position - 1].items
                findProductsButton.text = when {
                    plan.periodDays == 1 || weeks.isEmpty() -> "Найти товары для рациона с ИИ"
                    weeks.size == 1 -> "Найти товары для недели с ИИ"
                    position == 0 -> "Найти товары для первой недели с ИИ"
                    else -> "Найти товары для недели $position с ИИ"
                }
                val scope = if (weeks.size > 1 && position > 0)
                    weeks[position - 1].let { "${it.startDay}-${it.endDay}" } else "all"
                renderShoppingChecklist(shoppingItems, plan, items, scope)
            }
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }

        resetButton.visibility = View.VISIBLE
    }

    private fun showCookingDetails(plan: PlanResponse, dayIndex: Int, meal: PlanMeal) {
        val batch = PlanCookingDetails.batch(plan, dayIndex, meal)
        val instructions = meal.instructions?.takeIf { it.isNotBlank() }
            ?: "У этого сохранённого плана нет инструкции. Откройте блюдо в книге рецептов."
        val ingredients = batch.ingredients.joinToString("\n") {
            "• ${it.product}: ${FridgeInputParser.formatGrams(it.grams)} г"
        }.ifBlank { "Состав не сохранён в этом плане." }
        val action = if (meal.timeKind == "reheat")
            "По плану сегодня разогрев порции, запланированной к приготовлению в день ${batch.preparedOnDay + 1}. Ниже — ингредиенты на всю заготовку.\n\n"
        else ""
        val text = action + "Ингредиенты на ${batch.portions} порц.:\n$ingredients\n\n" +
            (if (batch.cookingWaterMl > 0) "Вода для основы: ${FridgeInputParser.formatGrams(batch.cookingWaterMl)} мл.\n\n" else "") +
            "Вес продуктов указан до приготовления; вес готового блюда может отличаться.\n\n" +
            "Как приготовить:\n$instructions\n\n" +
            "Калорийность одной порции: ${meal.calories} ккал (оценка).\n" +
            (meal.nutritionSource ?: "Источник расчёта не сохранён.") +
            (meal.recipeSourceUrl?.let { "\n\nОснова рецепта: $it\n${meal.recipeAdaptationNote.orEmpty()}" } ?: "")
        val scroll = ScrollView(this).apply { addView(planText(text).apply {
            android.text.util.Linkify.addLinks(this, android.text.util.Linkify.WEB_URLS)
            movementMethod = android.text.method.LinkMovementMethod.getInstance()
        }) }
        androidx.appcompat.app.AlertDialog.Builder(this).setTitle(meal.recipe)
            .setView(scroll).setPositiveButton("Понятно", null).show()
    }

    private fun renderShoppingChecklist(parent: LinearLayout, plan: PlanResponse, items: List<ShoppingItem>, scope: String) {
        parent.removeAllViews()
        if (items.isEmpty()) {
            parent.addView(planText("Дополнительные покупки не требуются."))
            return
        }
        // A server-generated revision identifies one user's exact saved menu.
        val key = ShoppingChecklist.key(plan, items, scope)
        val identity = ShoppingChecklist.identity(plan)
        val prefs = getSharedPreferences("porcia_shopping", MODE_PRIVATE)
        val checked = key?.let { prefs.getStringSet(it, emptySet())?.toMutableSet() } ?: mutableSetOf()
        val count = planText("")
        parent.addView(count)
        fun updateCount() { count.text = "Куплено ${items.count { it.product in checked }} из ${items.size}" }
        updateCount()
        items.forEach { item ->
            parent.addView(CheckBox(this).apply {
                text = "${item.product}: нужно ${item.grams} г\n" +
                    "Ориентир: ${item.packagesToBuy} уп. по ${item.packageGrams} г; остаток ${item.expectedLeftoverGrams} г"
                minHeight = (48 * resources.displayMetrics.density).toInt()
                setTextColor(androidx.core.content.ContextCompat.getColor(this@PlanActivity, R.color.nutriplan_text))
                isChecked = item.product in checked
                setOnCheckedChangeListener { _, selected ->
                    if (selected) checked.add(item.product) else checked.remove(item.product)
                    if (key != null) {
                        // Preserve period selections in this menu, but discard obsolete menus.
                        val editor = prefs.edit()
                        prefs.all.keys.filterNot { it.startsWith("$identity:") }.forEach { editor.remove(it) }
                        editor.putStringSet(key, checked.toSet()).apply()
                    }
                    updateCount()
                }
            })
        }
    }

    private fun <T> Call<T>.enqueueMutation(callback: Callback<T>) = enqueueTracked(callback, mutation = true)

    private fun <T> Call<T>.enqueueTracked(callback: Callback<T>, mutation: Boolean = false) {
        pendingCalls.add(this)
        if (mutation) {
            operation.request = this
            operation.pending.value = true
        }
        enqueue(object : Callback<T> {
            override fun onResponse(call: Call<T>, response: Response<T>) {
                pendingCalls.remove(call)
                if (!isDestroyed && !isFinishing && !call.isCanceled) callback.onResponse(call, response)
                if (mutation) operation.complete()
            }
            override fun onFailure(call: Call<T>, error: Throwable) {
                pendingCalls.remove(call)
                if (!isDestroyed && !isFinishing && !call.isCanceled) callback.onFailure(call, error)
                if (mutation) operation.complete()
            }
        })
    }

    override fun onDestroy() {
        pendingCalls.toList().filter { it !== operation.request }.forEach { it.cancel() }
        pendingCalls.clear()
        super.onDestroy()
    }

    private fun planText(value: String) = TextView(this).apply {
        text = value
        textSize = 16f
        setTextColor(androidx.core.content.ContextCompat.getColor(this@PlanActivity, R.color.nutriplan_text))
        val padding = (12 * resources.displayMetrics.density).toInt()
        setPadding(padding, padding, padding, padding)
    }

    private fun expandable(parent: LinearLayout, title: String, expanded: Boolean): LinearLayout {
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = if (expanded) View.VISIBLE else View.GONE
        }
        val toggle = PorciaUi.action(this, title).apply {
            isAllCaps = false
            text = (if (expanded) "▼ " else "▶ ") + title
            ViewCompat.setStateDescription(this, if (expanded) "Развёрнуто" else "Свёрнуто")
            setTextColor(androidx.core.content.ContextCompat.getColor(this@PlanActivity, R.color.nutriplan_on_soft))
            backgroundTintList = android.content.res.ColorStateList.valueOf(androidx.core.content.ContextCompat.getColor(this@PlanActivity, R.color.nutriplan_soft))
            setOnClickListener {
                val open = body.visibility != View.VISIBLE
                body.visibility = if (open) View.VISIBLE else View.GONE
                text = (if (open) "▼ " else "▶ ") + title
                ViewCompat.setStateDescription(this, if (open) "Развёрнуто" else "Свёрнуто")
            }
        }
        parent.addView(toggle)
        parent.addView(body)
        return body
    }

    private fun chooseReplacement(plan: PlanResponse, dayIndex: Int, meal: String) {
        val labels = arrayOf("Другое блюдо", "Дешевле по оценке каталога", "Быстрее приготовить", "С учётом исходного запаса")
        val reasons = listOf("different", "cheaper", "faster", "pantry")
        androidx.appcompat.app.AlertDialog.Builder(this)
            .setTitle("Замена: $meal")
            .setMessage("Если это заготовка, заменятся все связанные порции. Остальное меню сохранится. Учитывается запас на момент формирования меню; недостающие продукты попадут в закупку.")
            .setPositiveButton("Выбрать условие") { _, _ ->
                androidx.appcompat.app.AlertDialog.Builder(this)
                    .setTitle("Какое блюдо подобрать?")
                    .setItems(labels) { _, index -> replaceMeal(plan, dayIndex, meal, reasons[index]) }
                    .setNegativeButton("Отмена", null).show()
            }.setNegativeButton("Отмена", null).show()
    }

    private fun replaceMeal(plan: PlanResponse, dayIndex: Int, meal: String, reason: String) {
        if (busy) return
        val revision = plan.revision ?: return
        val token = getToken() ?: return
        showLoading(true)
        ApiClient.service.replaceMeal("Bearer $token", MealReplacementRequest(revision, dayIndex, meal, reason))
            .enqueueMutation(object : Callback<PlanResponse> {
                override fun onResponse(call: Call<PlanResponse>, response: Response<PlanResponse>) {
                    showLoading(false)
                    val updated = response.body()
                    if (response.isSuccessful && updated != null) {
                        showPlan(updated)
                        val fallback = when (updated.replacement?.aiStatus) {
                            "unavailable" -> " ИИ не ответил: использован подбор по правилам."
                            "invalid_response" -> " Ответ ИИ отклонён: использован подбор по правилам."
                            else -> ""
                        }
                        Toast.makeText(this@PlanActivity, (updated.replacement?.message ?: "Блюдо заменено") + fallback, Toast.LENGTH_LONG).show()
                    } else {
                        val detail = runCatching {
                            com.google.gson.JsonParser.parseString(response.errorBody()?.string().orEmpty())
                                .asJsonObject.get("detail")?.asString
                        }.getOrNull() ?: "Не удалось заменить блюдо. Код: ${response.code()}"
                        Toast.makeText(this@PlanActivity, detail, Toast.LENGTH_LONG).show()
                        if (response.code() == 409) loadCurrentPlan()
                    }
                }
                override fun onFailure(call: Call<PlanResponse>, error: Throwable) {
                    showLoading(false)
                    Toast.makeText(this@PlanActivity, "Связь прервалась. Проверяем сохранённый план…", Toast.LENGTH_LONG).show()
                    loadCurrentPlan()
                }
            })
    }

    private fun showLoading(loading: Boolean) {
        busy = loading
        replaceButtons.forEach { it.isEnabled = !loading }
        progress.visibility = if (loading) View.VISIBLE else View.GONE
        generateButton.isEnabled = !loading
        resetButton.isEnabled = !loading
        periodSpinner.isEnabled = !loading
        modeSpinner.isEnabled = !loading
        desiredInput.isEnabled = !loading
        wishInput.isEnabled = !loading
        wishButton.isEnabled = !loading
        surpriseCheckBox.isEnabled = !loading
        useFridgeCheckBox.isEnabled = !loading
    }

    private fun getToken(): String? {
        val token = getSharedPreferences(
            "nutriplan_session",
            MODE_PRIVATE
        ).getString("access_token", null)

        if (token == null) {
            result.text = "Сессия истекла. Выполните вход заново."
        }

        return token
    }
}

