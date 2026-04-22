package com.micky.phone

import android.content.Context
import android.content.SharedPreferences

object Prefs {
    private const val FILE = "micky"
    const val KEY_HOST = "host"
    const val KEY_PORT = "port"
    const val KEY_MODE = "mode"
    const val KEY_FX = "fx"
    const val KEY_GAIN = "gain"

    fun get(context: Context): SharedPreferences =
        context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)
}
