package com.micky.phone

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View
import kotlin.math.max

/** Custom segmented VU meter — matches the PC app style. */
class VuView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyle: Int = 0
) : View(context, attrs, defStyle) {

    private val segments = 36
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rect = RectF()
    private var level = 0f
    private var peak = 0f
    private var peakHoldTicks = 0

    fun setLevel(v: Float) {
        level = v.coerceIn(0f, 1f)
        if (level > peak) {
            peak = level
            peakHoldTicks = 20
        } else {
            peakHoldTicks--
            if (peakHoldTicks <= 0) peak = max(0f, peak - 0.02f)
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        val r = h * 0.22f

        // background
        paint.color = Color.parseColor("#1d2430")
        rect.set(0f, 0f, w, h)
        canvas.drawRoundRect(rect, r, r, paint)

        val pad = h * 0.18f
        val segW = (w - pad * 2) / segments
        val lit = (level * segments).toInt()
        for (i in 0 until segments) {
            val ratio = i.toFloat() / (segments - 1)
            val color = when {
                ratio < 0.65f -> Color.parseColor("#8affc1")
                ratio < 0.85f -> Color.parseColor("#ffd166")
                else -> Color.parseColor("#ff6b6b")
            }
            paint.color = if (i < lit) color else Color.parseColor("#2a3140")
            val x = pad + i * segW
            rect.set(x + segW * 0.08f, pad, x + segW * 0.92f, h - pad)
            canvas.drawRoundRect(rect, 2f, 2f, paint)
        }

        if (peak > 0f) {
            val px = pad + peak * (w - pad * 2)
            paint.color = Color.WHITE
            rect.set(px - 1.5f, pad * 0.5f, px + 1.5f, h - pad * 0.5f)
            canvas.drawRect(rect, paint)
        }
    }
}
