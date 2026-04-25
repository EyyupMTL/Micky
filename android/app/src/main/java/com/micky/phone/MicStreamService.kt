package com.micky.phone

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.io.IOException
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.concurrent.thread
import kotlin.math.min
import kotlin.math.sqrt

class MicStreamService : Service() {

    @Volatile private var running = false
    @Volatile private var muted = false
    private var streamThread: Thread? = null
    private var readerThread: Thread? = null
    private var sock: Socket? = null
    private var out: OutputStream? = null
    private var wakeLock: PowerManager.WakeLock? = null

    private lateinit var localMode: String
    private var micChoice: String = Prefs.MIC_AUTO

    override fun onBind(intent: Intent?): IBinder? = null

    @SuppressLint("MissingPermission")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action ?: ACTION_START
        when (action) {
            ACTION_STOP -> {
                stopStreaming()
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_MUTE -> {
                val m = intent?.getBooleanExtra(EXTRA_MUTED, false) ?: false
                muted = m
                State.muted.postValue(m)
                sendMuteAsync(m)
                return START_STICKY
            }
            ACTION_FX -> {
                val preset = intent?.getStringExtra(EXTRA_FX) ?: "normal"
                State.fx.postValue(preset)
                sendFxAsync(preset)
                return START_STICKY
            }
            ACTION_GAIN -> {
                val g = intent?.getFloatExtra(EXTRA_GAIN, 1.0f) ?: 1.0f
                State.gain.postValue(g)
                sendGainAsync(g)
                return START_STICKY
            }
            ACTION_START -> {
                if (running) return START_STICKY
                val host = intent?.getStringExtra(EXTRA_HOST) ?: return START_NOT_STICKY
                val port = intent.getIntExtra(EXTRA_PORT, 8125)
                localMode = intent.getStringExtra(EXTRA_MODE) ?: MODE_WIFI
                micChoice = intent.getStringExtra(EXTRA_MIC) ?: Prefs.MIC_AUTO
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                    != PackageManager.PERMISSION_GRANTED
                ) {
                    State.status.postValue("Mikrofon izni yok")
                    stopSelf()
                    return START_NOT_STICKY
                }
                startForeground(NOTIF_ID, buildNotification("Bağlanılıyor…"), fgTypeMicrophone())
                acquireWakeLock()
                startStreaming(host, port)
            }
        }
        return START_STICKY
    }

    private fun fgTypeMicrophone(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        else 0

    private fun acquireWakeLock() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Micky:stream").apply {
            setReferenceCounted(false)
            acquire(TEN_MIN)
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let { if (it.isHeld) it.release() }
        wakeLock = null
    }

    @SuppressLint("MissingPermission")
    private fun startStreaming(host: String, port: Int) {
        running = true
        State.status.postValue("Bağlanılıyor $host:$port …")
        State.connected.postValue(false)
        State.mismatch.postValue(null)

        streamThread = thread(name = "micky-stream", isDaemon = true) {
            val sampleRate = 48000
            val channels = 1
            val minBuf = AudioRecord.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            val bufSize = maxOf(minBuf, 4096) * 2
            var record: AudioRecord? = null
            try {
                // Source priority for routing to the TOP/BACK mic:
                //   CAMCORDER  — OEM-routed to the video-record capsule (top/back)
                //   UNPROCESSED— raw, usually the bottom close-talk capsule
                //   MIC        — system default, usually bottom
                record = openRecord(MediaRecorder.AudioSource.CAMCORDER, sampleRate, bufSize)
                    ?: openRecord(MediaRecorder.AudioSource.UNPROCESSED, sampleRate, bufSize)
                    ?: openRecord(MediaRecorder.AudioSource.MIC, sampleRate, bufSize)
                if (record == null || record.state != AudioRecord.STATE_INITIALIZED) {
                    State.status.postValue("Mikrofon başlatılamadı")
                    return@thread
                }
                // Pin to the chosen physical mic (top/bottom/default/auto).
                applyMicChoice(record, micChoice)
                // Disable AGC/NS/AEC the platform may still attach.
                disableHardwareFx(record.audioSessionId)

                val s = Socket()
                s.connect(InetSocketAddress(host, port), 5000)
                s.tcpNoDelay = true
                sock = s
                val o = s.getOutputStream()
                out = o
                val input = s.getInputStream()

                // Handshake (same as v1)
                val header = ByteBuffer.allocate(12).order(ByteOrder.LITTLE_ENDIAN)
                header.put("MIKY".toByteArray(Charsets.US_ASCII))
                header.putInt(sampleRate)
                header.putShort(channels.toShort())
                header.putShort(16.toShort())
                o.write(header.array())
                o.flush()

                val ack = ByteArray(2)
                var got = 0
                while (got < 2) {
                    val r = input.read(ack, got, 2 - got)
                    if (r < 0) { State.status.postValue("El sıkışma kesildi"); return@thread }
                    got += r
                }
                if (ack[0] != 'O'.code.toByte() || ack[1] != 'K'.code.toByte()) {
                    State.status.postValue("El sıkışma başarısız")
                    return@thread
                }

                // Tell server our mode and current mute state
                Frames.write(o, Frames.TYPE_MODE, localMode.toByteArray(Charsets.UTF_8))
                Frames.write(o, Frames.TYPE_MUTE, byteArrayOf(if (muted) 1 else 0))

                State.connected.postValue(true)
                State.status.postValue("Yayınlanıyor → $host:$port")

                // Reader: receive MUTE, MODE, PING from server
                readerThread = thread(name = "micky-reader", isDaemon = true) {
                    try {
                        while (running) {
                            val frame = try {
                                Frames.read(input)
                            } catch (_: Exception) {
                                null
                            } ?: break
                            val (type, payload) = frame
                            when (type) {
                                Frames.TYPE_MUTE -> {
                                    val m = payload.isNotEmpty() && payload[0].toInt() != 0
                                    muted = m
                                    State.muted.postValue(m)
                                }
                                Frames.TYPE_MODE -> {
                                    val serverMode = String(payload, Charsets.UTF_8)
                                    State.serverMode.postValue(serverMode)
                                    if (serverMode.isNotEmpty() && serverMode != localMode) {
                                        State.mismatch.postValue(serverMode)
                                    } else {
                                        State.mismatch.postValue(null)
                                    }
                                }
                                Frames.TYPE_PING -> {
                                    try { Frames.write(o, Frames.TYPE_PING) } catch (_: Exception) {}
                                }
                                Frames.TYPE_FX -> {
                                    val preset = String(payload, Charsets.UTF_8)
                                    if (preset.isNotEmpty()) State.fx.postValue(preset)
                                }
                                Frames.TYPE_GAIN -> {
                                    if (payload.size >= 4) {
                                        val g = java.nio.ByteBuffer.wrap(payload, 0, 4)
                                            .order(java.nio.ByteOrder.LITTLE_ENDIAN)
                                            .float
                                        State.gain.postValue(g.coerceIn(0f, 3f))
                                    }
                                }
                                else -> { /* ignore */ }
                            }
                        }
                    } catch (_: Throwable) {
                        /* swallow so thread exit is clean */
                    }
                }

                record.startRecording()
                val block = ShortArray(1024)
                val byteBuf = ByteBuffer.allocate(block.size * 2).order(ByteOrder.LITTLE_ENDIAN)
                while (running && !Thread.currentThread().isInterrupted) {
                    val n = record.read(block, 0, block.size)
                    if (n <= 0) continue
                    byteBuf.clear()
                    if (muted) {
                        for (i in 0 until n) byteBuf.putShort(0)
                    } else {
                        for (i in 0 until n) byteBuf.putShort(block[i])
                    }
                    val bytes = ByteArray(n * 2)
                    System.arraycopy(byteBuf.array(), 0, bytes, 0, bytes.size)
                    try {
                        Frames.write(o, Frames.TYPE_AUDIO, bytes)
                    } catch (e: IOException) {
                        break
                    }

                    if (muted) {
                        State.level.postValue(0f)
                    } else {
                        var sumSq = 0.0
                        for (i in 0 until n) {
                            val v = block[i].toDouble()
                            sumSq += v * v
                        }
                        val rms = sqrt(sumSq / n) / 32768.0
                        State.level.postValue(min(1.0, rms * 3.0).toFloat())
                    }
                }
            } catch (e: IOException) {
                State.status.postValue("Hata: ${e.message}")
            } catch (e: SecurityException) {
                State.status.postValue("İzin reddedildi")
            } finally {
                running = false
                State.connected.postValue(false)
                State.mismatch.postValue(null)
                try { record?.stop() } catch (_: Exception) {}
                try { record?.release() } catch (_: Exception) {}
                try { out?.close() } catch (_: Exception) {}
                try { sock?.close() } catch (_: Exception) {}
                out = null; sock = null
                readerThread?.interrupt()
                readerThread = null
                State.level.postValue(0f)
                State.status.postValue("Bağlantı kapandı")
                stopForeground(STOP_FOREGROUND_REMOVE)
                releaseWakeLock()
                stopSelf()
            }
        }
    }

    private fun stopStreaming() {
        running = false
        streamThread?.interrupt()
    }

    @SuppressLint("MissingPermission")
    private fun openRecord(source: Int, sampleRate: Int, bufSize: Int): AudioRecord? {
        return try {
            val r = AudioRecord(
                source,
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize,
            )
            if (r.state == AudioRecord.STATE_INITIALIZED) r
            else { try { r.release() } catch (_: Exception) {}; null }
        } catch (_: Throwable) { null }
    }

    /** Turn off platform-attached audio effects that cause "volume pumping". */
    private fun disableHardwareFx(sessionId: Int) {
        try {
            val c = android.media.audiofx.AutomaticGainControl.create(sessionId)
            c?.enabled = false
        } catch (_: Throwable) {}
        try {
            val n = android.media.audiofx.NoiseSuppressor.create(sessionId)
            n?.enabled = false
        } catch (_: Throwable) {}
        try {
            val a = android.media.audiofx.AcousticEchoCanceler.create(sessionId)
            a?.enabled = false
        } catch (_: Throwable) {}
    }

    /**
     * Pin [record] to the user-chosen physical mic.
     *  - "default": don't touch — let the system pick.
     *  - "top"    : highest Y coordinate (back/top capsule, Android convention).
     *  - "bottom" : lowest  Y coordinate (front/talk capsule).
     *  - "auto"   : same as "top" (the back-mic is what users actually want).
     */
    @SuppressLint("MissingPermission")
    private fun applyMicChoice(record: AudioRecord, choice: String) {
        if (choice == Prefs.MIC_DEFAULT) {
            State.status.postValue("Mikrofon: sistem varsayılanı")
            return
        }
        try {
            val am = getSystemService(AUDIO_SERVICE) as android.media.AudioManager
            val inputs = am.getDevices(android.media.AudioManager.GET_DEVICES_INPUTS)
            val builtIn = inputs.filter {
                it.type == android.media.AudioDeviceInfo.TYPE_BUILTIN_MIC
            }
            if (builtIn.isEmpty()) return

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val mics = try { am.microphones } catch (_: Throwable) { emptyList() }
                val positioned = mics
                    .filter { it.type == android.media.AudioDeviceInfo.TYPE_BUILTIN_MIC }
                    .filter {
                        val p = it.position
                        p != null && p.y != android.media.MicrophoneInfo.POSITION_UNKNOWN.y
                    }
                val pick = when (choice) {
                    Prefs.MIC_BOTTOM -> positioned.minByOrNull { it.position.y }
                    else -> positioned.maxByOrNull { it.position.y } // top / auto
                }
                if (pick != null) {
                    val match = builtIn.firstOrNull { it.address == pick.address }
                        ?: builtIn.firstOrNull { it.id == pick.id }
                    if (match != null) {
                        record.preferredDevice = match
                        val label = if (choice == Prefs.MIC_BOTTOM) "alt" else "üst"
                        val desc = pick.description ?: "y=${"%.2f".format(pick.position.y)}"
                        State.status.postValue("Mikrofon: $label ($desc)")
                        return
                    }
                }
            }

            // Pre-API-28 fallback: best effort by index (assume index 1 = top)
            if (builtIn.size > 1) {
                val mic = if (choice == Prefs.MIC_BOTTOM) builtIn.first()
                          else builtIn.drop(1).first()
                record.preferredDevice = mic
                State.status.postValue(
                    if (choice == Prefs.MIC_BOTTOM) "Mikrofon: alt (varsayılan)"
                    else "Mikrofon: üst (ikinci yerleşik)"
                )
            }
        } catch (_: Throwable) {
            /* ignore — stay on default */
        }
    }

    /** Fire-and-forget control write off the main thread so mute never ANRs the UI. */
    private fun sendMuteAsync(m: Boolean) {
        val o = out ?: return
        thread(isDaemon = true, name = "micky-ctl") {
            try {
                Frames.write(o, Frames.TYPE_MUTE, byteArrayOf(if (m) 1 else 0))
            } catch (_: Exception) { /* socket closed */ }
        }
    }

    private fun sendFxAsync(preset: String) {
        val o = out ?: return
        thread(isDaemon = true, name = "micky-ctl") {
            try {
                Frames.write(o, Frames.TYPE_FX, preset.toByteArray(Charsets.UTF_8))
            } catch (_: Exception) { /* socket closed */ }
        }
    }

    private fun sendGainAsync(gain: Float) {
        val o = out ?: return
        thread(isDaemon = true, name = "micky-ctl") {
            try {
                val bb = java.nio.ByteBuffer.allocate(4).order(java.nio.ByteOrder.LITTLE_ENDIAN)
                bb.putFloat(gain.coerceIn(0f, 3f))
                Frames.write(o, Frames.TYPE_GAIN, bb.array())
            } catch (_: Exception) { /* socket closed */ }
        }
    }

    private fun buildNotification(text: String): Notification {
        val stopIntent = Intent(this, MicStreamService::class.java).setAction(ACTION_STOP)
        val stopPi = PendingIntent.getService(
            this, 1, stopIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val openIntent = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val openPi = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, MickyApp.CHANNEL_ID)
            .setContentTitle("Micky")
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_mic)
            .setOngoing(true)
            .setContentIntent(openPi)
            .addAction(R.drawable.ic_stop, "Durdur", stopPi)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    override fun onDestroy() {
        super.onDestroy()
        running = false
        releaseWakeLock()
    }

    companion object {
        const val ACTION_START = "com.micky.phone.START"
        const val ACTION_STOP = "com.micky.phone.STOP"
        const val ACTION_MUTE = "com.micky.phone.MUTE"
        const val ACTION_FX = "com.micky.phone.FX"
        const val ACTION_GAIN = "com.micky.phone.GAIN"
        const val EXTRA_HOST = "host"
        const val EXTRA_PORT = "port"
        const val EXTRA_MUTED = "muted"
        const val EXTRA_MODE = "mode"
        const val EXTRA_FX = "fx"
        const val EXTRA_GAIN = "gain"
        const val EXTRA_MIC = "mic"
        const val NOTIF_ID = 101
        const val TEN_MIN = 10L * 60 * 1000
    }
}
