package ru.pershin.nutriplan

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Typeface
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import com.google.android.material.button.MaterialButton

/** Shared native components for the chosen Ladno visual language. */
object PorciaUi {
    fun dp(context: Context, value: Int) = (value * context.resources.displayMetrics.density).toInt()

    fun text(context: Context, value: String, size: Float = 15f, muted: Boolean = false, bold: Boolean = false) = TextView(context).apply {
        text = value
        textSize = size
        setTextColor(ContextCompat.getColor(context, if (muted) R.color.nutriplan_muted else R.color.nutriplan_text))
        if (bold) setTypeface(typeface, Typeface.BOLD)
        setLineSpacing(dp(context, 3).toFloat(), 1f)
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(context, 8) }
    }

    fun card(context: Context) = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        setBackgroundResource(R.drawable.porcia_card)
        setPadding(dp(context, 16), dp(context, 16), dp(context, 16), dp(context, 12))
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(context, 12) }
    }

    fun badge(context: Context, value: String) = text(context, value, 13f).apply {
        setTextColor(ContextCompat.getColor(context, R.color.nutriplan_on_soft))
        setBackgroundResource(R.drawable.porcia_tint)
        setPadding(dp(context, 10), dp(context, 7), dp(context, 10), dp(context, 7))
        layoutParams = LinearLayout.LayoutParams(-2, -2).apply { bottomMargin = dp(context, 12) }
    }

    fun action(context: Context, label: String, primary: Boolean = false) = MaterialButton(context).apply {
        text = label
        isAllCaps = false
        letterSpacing = 0f
        elevation = 0f
        stateListAnimator = null
        textSize = 14f
        minHeight = dp(context, 48)
        insetTop = 0
        insetBottom = 0
        cornerRadius = dp(context, 12)
        backgroundTintList = ColorStateList.valueOf(ContextCompat.getColor(context,
            if (primary) R.color.nutriplan_green else R.color.nutriplan_soft))
        setTextColor(ContextCompat.getColor(context,
            if (primary) R.color.nutriplan_on_primary else R.color.nutriplan_on_soft))
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(context, 4) }
    }
}
