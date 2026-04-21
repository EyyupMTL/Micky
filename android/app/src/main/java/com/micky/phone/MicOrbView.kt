package com.micky.phone

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import kotlin.math.max
import kotlin.math.min

/**
 * Large circular mic button. Pulses outward with voice level,
 * taps to toggle mute, color reflects connected/muted state.
 */
class MicOrbView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
    defStyle: Int = 0
) : View(context, attrs, defStyle) {

    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var level = 0f
    private var smoothedLevel = 0f
    var connected: Boolean = false
        set(v) { field = v; invalidate() }
    var muted: Boolean = false
        set(v) { field = v; invalidate() }

    init {
        isClickable = true
        isFocusable = true
    }

    fun setLevel(v: Float) {
        level = v.coerceIn(0f, 1f)
        // Smooth rise/fall
        smoothedLevel = if (level > smoothedLevel) {
            0.5f * smoothedLevel + 0.5f * level
        } else {
            0.85f * smoothedLevel + 0.15f * level
        }
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val maxR = min(width, height) / 2f - 8f

        val mainR = maxR * 0.62f
        val pulseR = mainR + (maxR - mainR) * smoothedLevel

        val accent = Color.parseColor("#8affc1")
        val accentDim = Color.parseColor("#5cc98a")
        val red = Color.parseColor("#ff6b6b")
        val dim = Color.parseColor("#2a3140")
        val ink = Color.parseColor("#0a1a10")

        // Pulse ring (translucent)
        paint.style = Paint.Style.FILL
        paint.color = when {
            !connected -> Color.argb(40, 138, 255, 193)
            muted -> Color.argb(60, 255, 107, 107)
            else -> Color.argb(60, 138, 255, 193)
        }
        canvas.drawCircle(cx, cy, pulseR, paint)

        // Ring outline at max
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f
        paint.color = Color.argb(30, 138, 255, 193)
        canvas.drawCircle(cx, cy, maxR, paint)

        // Main filled circle
        paint.style = Paint.Style.FILL
        paint.color = when {
            !connected -> dim
            muted -> red
            else -> accent
        }
        canvas.drawCircle(cx, cy, mainR, paint)

        // Mic icon inside
        paint.color = when {
            !connected -> Color.parseColor("#8b96a7")
            muted -> Color.WHITE
            else -> ink
        }
        drawMic(canvas, cx, cy, mainR * 0.48f, muted)
    }

    private fun drawMic(canvas: Canvas, cx: Float, cy: Float, size: Float, crossed: Boolean) {
        paint.style = Paint.Style.FILL
        // Capsule body
        val w = size * 0.55f
        val h = size * 0.95f
        val top = cy - h * 0.55f
        val bottom = cy + h * 0.1f
        canvas.drawRoundRect(cx - w / 2f, top, cx + w / 2f, bottom, w / 2f, w / 2f, paint)
        // Arc cradle
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = max(3f, size * 0.08f)
        paint.strokeCap = Paint.Cap.ROUND
        val arcSize = h * 0.72f
        canvas.drawArc(
            cx - arcSize * 0.5f, cy - arcSize * 0.3f,
            cx + arcSize * 0.5f, cy + arcSize * 0.7f,
            20f, 140f, false, paint
        )
        // Stem
        canvas.drawLine(cx, cy + arcSize * 0.5f, cx, cy + arcSize * 0.75f, paint)
        // Base
        canvas.drawLine(cx - w * 0.5f, cy + arcSize * 0.8f, cx + w * 0.5f, cy + arcSize * 0.8f, paint)
        if (crossed) {
            paint.strokeWidth = max(4f, size * 0.1f)
            val d = size * 1.1f
            canvas.drawLine(cx - d / 2f, cy - d / 2f, cx + d / 2f, cy + d / 2f, paint)
        }
        paint.style = Paint.Style.FILL
    }
}
