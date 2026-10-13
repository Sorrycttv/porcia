package ru.pershin.nutriplan

import android.os.Bundle
import android.view.View
import android.view.inputmethod.InputMethodManager
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

data class ChatMessage(
    val text: String,
    val fromUser: Boolean
)

class activity_acriv_coach : AppCompatActivity() {

    // Элементы экрана.
    private lateinit var questionInput: EditText
    private lateinit var messagesContainer: LinearLayout
    private lateinit var answerScroll: ScrollView
    private lateinit var progressBar: ProgressBar
    private lateinit var sendButton: Button
    private val messages = mutableListOf<ChatMessage>()
    private val gson = Gson()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // Подключчние разметки
        setContentView(R.layout.activity_activ_coach)

        // элементы разметки по их ID
        questionInput = findViewById(R.id.coachQuestionInput)
        messagesContainer = findViewById(R.id.coachMessagesContainer)
        answerScroll = findViewById(R.id.coachAnswerScroll)
        progressBar = findViewById(R.id.coachProgressBar)
        sendButton = findViewById(R.id.sendCoachButton)


        findViewById<Button>(R.id.clearCoachHistoryButton).setOnClickListener {
            confirmHistoryClearing()
        }

        loadHistory()

        sendButton.setOnClickListener {
            sendQuestion()
        }

        // Учитываем верхнюю и нижнюю системные панели Android.
        val rootView = findViewById<View>(R.id.main)
        val initialLeft = rootView.paddingLeft
        val initialTop = rootView.paddingTop
        val initialRight = rootView.paddingRight
        val initialBottom = rootView.paddingBottom

        ViewCompat.setOnApplyWindowInsetsListener(rootView) { view, insets ->
            val systemBars = insets.getInsets(
                WindowInsetsCompat.Type.systemBars()
            )

            view.setPadding(
                initialLeft + systemBars.left,
                initialTop + systemBars.top,
                initialRight + systemBars.right,
                initialBottom + systemBars.bottom
            )

            insets
        }
    }

    private fun sendQuestion() {
        val question = questionInput.text.toString().trim()

        if (question.length < 2) {
            questionInput.error = "Введите вопрос коучу"
            return
        }

        val token = getSharedPreferences(
            "nutriplan_session",
            MODE_PRIVATE
        ).getString("access_token", null)

        if (token == null) {
            addMessage("Сессия истекла. Выполните вход ещё раз.", false)
            return
        }

        addMessage(question, true)
        questionInput.text.clear()
        showLoading(true)
        hideKeyboard()

        val history = messages
            .dropLast(1)
            .takeLast(12)
            .map { message ->
                CoachHistoryItem(
                    role = if (message.fromUser) "user" else "assistant",
                    content = message.text.take(2000)
                )
            }

        ApiClient.service.sendCoachMessage(
            authorization = "Bearer $token",
            request = CoachRequest(
                message = question,
                history = history
            )
        ).enqueue(object : Callback<CoachResponse> {

            override fun onResponse(
                call: Call<CoachResponse>,
                response: Response<CoachResponse>
            ) {
                showLoading(false)

                val coachResponse = response.body()

                if (response.isSuccessful && coachResponse != null) {
                    addMessage(coachResponse.answer, false)
                } else {
                    val errorMessage = when (response.code()) {
                        400 -> "Сервер не смог обработать вопрос."
                        401 -> "Сессия истекла. Выполните вход ещё раз."
                        422 -> "Не удалось обработать историю чата. Повторите вопрос."
                        404 -> "Сервис коуча сейчас недоступен."
                        else -> "Не удалось получить ответ. Код: ${response.code()}"
                    }
                    addMessage(errorMessage, false)
                }
            }

            override fun onFailure(
                call: Call<CoachResponse>,
                error: Throwable
            ) {
                showLoading(false)

                addMessage(
                    "Нет связи с сервером. Проверьте интернет и повторите попытку.",
                    false
                )
            }
        })
    }

    private fun addMessage(text: String, fromUser: Boolean) {
        val message = ChatMessage(text, fromUser)
        messages.add(message)

        if (messages.size > 40) {
            messages.removeAt(0)
            renderHistory()
        } else {
            showMessageBubble(message)
        }

        saveHistory()
        scrollToBottom()
    }

    private fun showMessageBubble(message: ChatMessage) {
        val bubble = TextView(this)
        bubble.text = cleanDisplayText(message.text)
        bubble.textSize = 16f
        bubble.setTextColor(
            androidx.core.content.ContextCompat.getColor(this@activity_acriv_coach,
                if (message.fromUser) R.color.nutriplan_on_primary else R.color.nutriplan_on_soft)
        )
        bubble.setPadding(dp(14), dp(11), dp(14), dp(11))

        bubble.background = GradientDrawable().apply {
            cornerRadius = dp(18).toFloat()
            setColor(
                if (message.fromUser) {
                    androidx.core.content.ContextCompat.getColor(this@activity_acriv_coach, R.color.nutriplan_green)
                } else {
                    androidx.core.content.ContextCompat.getColor(this@activity_acriv_coach, R.color.nutriplan_soft)
                }
            )
        }

        bubble.layoutParams = LinearLayout.LayoutParams(
            LinearLayout.LayoutParams.WRAP_CONTENT,
            LinearLayout.LayoutParams.WRAP_CONTENT
        ).apply {
            setMargins(
                if (message.fromUser) dp(48) else 0,
                dp(5),
                if (message.fromUser) 0 else dp(48),
                dp(5)
            )
            gravity = if (message.fromUser) Gravity.END else Gravity.START
        }

        messagesContainer.addView(bubble)
    }

    private fun cleanDisplayText(text: String): String {
        return text
            .replace("**", "")
            .replace(Regex("(?m)^#{1,6}\\s*"), "")
            .replace(Regex("(?m)^[-*]\\s+"), "• ")
    }

    private fun saveHistory() {
        getSharedPreferences("nutriplan_coach", MODE_PRIVATE)
            .edit()
            .putString("coach_history", gson.toJson(messages.takeLast(40)))
            .apply()
    }

    private fun loadHistory() {
        val savedJson = getSharedPreferences("nutriplan_coach", MODE_PRIVATE)
            .getString("coach_history", null)

        if (savedJson.isNullOrBlank()) {
            addMessage(
                "Здравствуйте! Я учту ваш профиль, рацион и продукты. Что вы хотите узнать?",
                false
            )
            return
        }

        try {
            val type = object : TypeToken<List<ChatMessage>>() {}.type
            val savedMessages: List<ChatMessage> = gson.fromJson(savedJson, type)
            messages.clear()
            messages.addAll(savedMessages.takeLast(40))
            renderHistory()
            scrollToBottom()
        } catch (error: Exception) {
            messages.clear()
            messagesContainer.removeAllViews()
            addMessage("Здравствуйте! Чем я могу помочь с вашим рационом?", false)
        }
    }

    private fun renderHistory() {
        messagesContainer.removeAllViews()
        messages.forEach { showMessageBubble(it) }
    }

    private fun confirmHistoryClearing() {
        AlertDialog.Builder(this)
            .setTitle("Очистить чат?")
            .setMessage("Все сохранённые сообщения коуча будут удалены с телефона.")
            .setNegativeButton("Отмена", null)
            .setPositiveButton("Очистить") { _, _ ->
                messages.clear()
                messagesContainer.removeAllViews()
                getSharedPreferences("nutriplan_coach", MODE_PRIVATE)
                    .edit()
                    .remove("coach_history")
                    .apply()
                addMessage(
                    "Здравствуйте! Я учту ваш профиль, рацион и продукты. Что вы хотите узнать?",
                    false
                )
            }
            .show()
    }

    private fun scrollToBottom() {

        // После ответа возвращаем область результата к началу.
        answerScroll.post {
            answerScroll.fullScroll(View.FOCUS_DOWN)
        }
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density).toInt()
    }

    private fun showLoading(isLoading: Boolean) {
        progressBar.visibility =
            if (isLoading) View.VISIBLE else View.GONE

        sendButton.isEnabled = !isLoading

    }

    private fun hideKeyboard() {
        val keyboard = getSystemService(
            Context.INPUT_METHOD_SERVICE
        ) as InputMethodManager

        keyboard.hideSoftInputFromWindow(
            questionInput.windowToken,
            0
        )
        questionInput.clearFocus()
    }
}
