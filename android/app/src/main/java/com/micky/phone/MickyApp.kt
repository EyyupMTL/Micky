package com.micky.phone

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build

class MickyApp : Application() {
    override fun onCreate() {
        super.onCreate()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Mikrofon yayını",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Micky mikrofon yayını aktifken gösterilir"
                setShowBadge(false)
            }
            nm.createNotificationChannel(channel)
        }
    }

    companion object {
        const val CHANNEL_ID = "micky_mic_stream"
    }
}
