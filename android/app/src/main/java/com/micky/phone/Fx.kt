package com.micky.phone

/** Voice-effect presets — must mirror pc/voice_fx.py PRESETS list. */
object Fx {
    val presets: List<Pair<String, String>> = listOf(
        "normal" to "Normal",
        "robot" to "Robot",
        "eko" to "Eko",
        "derin" to "Derin",
        "uzay" to "Uzay",
        "yuksek" to "Yüksek",
    )

    fun label(id: String): String = presets.firstOrNull { it.first == id }?.second ?: id
}
