package com.micky.phone

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothServerSocket
import android.bluetooth.BluetoothSocket
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID
import kotlin.concurrent.thread
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Phone-to-phone mic sharing over Bluetooth RFCOMM.
 *
 * Server (provides mic): listens on a well-known UUID, captures mic, streams
 *   raw 16 kHz PCM16 mono to the connected client.
 *
 * Client (consumes mic): connects to paired device, reads PCM and plays it
 *   via AudioTrack so the receiver phone's own mic (during video recording)
 *   captures the sound — effectively using the other phone as an external mic.
 */
class BluetoothMicService : Service() {

    @Volatile private var running = false
    private var thread: Thread? = null
    private var serverSocket: BluetoothServerSocket? = null
    private var socket: BluetoothSocket? = null

    override fun onBind(intent: Intent?): IBinder? = null

    @SuppressLint("MissingPermission")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action ?: ACTION_STOP) {
            ACTION_STOP -> { stopEverything(); stopSelf(); return START_NOT_STICKY }
            ACTION_START_SERVER -> startServer()
            ACTION_START_CLIENT -> {
                val addr = intent?.getStringExtra(EXTRA_DEVICE) ?: return START_NOT_STICKY
                startClient(addr)
            }
        }
        return START_STICKY
    }

    private fun fgTypeMicrophone(): Int =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        else 0

    // ---- Server mode -----------------------------------------------------
    @SuppressLint("MissingPermission")
    private fun startServer() {
        if (running) return
        if (!hasBtPerm(true)) {
            BtState.status.postValue("Bluetooth izni yok"); stopSelf(); return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            BtState.status.postValue("Mikrofon izni yok"); stopSelf(); return
        }
        val adapter = BluetoothAdapter.getDefaultAdapter()
        if (adapter == null || !adapter.isEnabled) {
            BtState.status.postValue("Bluetooth kapalı"); stopSelf(); return
        }
        startForeground(NOTIF_ID, buildNote("Eşleşme bekleniyor…"), fgTypeMicrophone())
        BtState.role.postValue(ROLE_SERVER)
        running = true
        thread = thread(name = "micky-bt-srv", isDaemon = true) {
            try {
                // Insecure variant accepts connections without requiring a
                // bonded link key on every Android version — more reliable
                // for first-time hookups.
                val ss = try {
                    adapter.listenUsingInsecureRfcommWithServiceRecord("MickyMic", MICKY_BT_UUID)
                } catch (_: Throwable) {
                    adapter.listenUsingRfcommWithServiceRecord("MickyMic", MICKY_BT_UUID)
                }
                serverSocket = ss
                BtState.status.postValue("Eşleşme bekleniyor… karşı telefonda 'Mikrofon Al' seç ve bu cihazı tıkla")
                val s = ss.accept()  // blocks
                ss.close(); serverSocket = null
                socket = s
                BtState.status.postValue("Bağlandı: ${s.remoteDevice.name ?: s.remoteDevice.address}")
                BtState.connected.postValue(true)
                streamMicTo(s.outputStream)
            } catch (e: Exception) {
                BtState.status.postValue("Sunucu hata: ${e.message}")
            } finally {
                running = false
                BtState.connected.postValue(false)
                BtState.level.postValue(0f)
                try { socket?.close() } catch (_: Exception) {}
                try { serverSocket?.close() } catch (_: Exception) {}
                socket = null; serverSocket = null
                stopForeground(STOP_FOREGROUND_REMOVE)
                BtState.status.postValue("Kapandı")
                stopSelf()
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun streamMicTo(out: OutputStream) {
        val sr = 16000
        val minBuf = AudioRecord.getMinBufferSize(
            sr, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        // UNPROCESSED → CAMCORDER → MIC, disable AGC/NS/AEC, prefer top mic.
        val bufBytes = maxOf(minBuf, 4096) * 2
        var record = tryOpen(MediaRecorder.AudioSource.UNPROCESSED, sr, bufBytes)
            ?: tryOpen(MediaRecorder.AudioSource.CAMCORDER, sr, bufBytes)
            ?: tryOpen(MediaRecorder.AudioSource.MIC, sr, bufBytes)
        if (record == null || record.state != AudioRecord.STATE_INITIALIZED) {
            BtState.status.postValue("Mikrofon başlatılamadı"); return
        }
        try {
            val am = getSystemService(AUDIO_SERVICE) as android.media.AudioManager
            val builtIn = am.getDevices(android.media.AudioManager.GET_DEVICES_INPUTS)
                .filter { it.type == android.media.AudioDeviceInfo.TYPE_BUILTIN_MIC }
            if (builtIn.size > 1) {
                record.preferredDevice = builtIn.drop(1).first()
            }
        } catch (_: Throwable) {}
        try { android.media.audiofx.AutomaticGainControl.create(record.audioSessionId)?.enabled = false } catch (_: Throwable) {}
        try { android.media.audiofx.NoiseSuppressor.create(record.audioSessionId)?.enabled = false } catch (_: Throwable) {}
        try { android.media.audiofx.AcousticEchoCanceler.create(record.audioSessionId)?.enabled = false } catch (_: Throwable) {}
        try {
            record.startRecording()
            val block = ShortArray(512)
            val bytes = ByteArray(block.size * 2)
            while (running && !Thread.currentThread().isInterrupted) {
                val n = record.read(block, 0, block.size)
                if (n <= 0) break
                var i = 0; var j = 0
                var sumSq = 0.0
                while (i < n) {
                    val v = block[i].toInt()
                    bytes[j] = (v and 0xFF).toByte()
                    bytes[j + 1] = ((v shr 8) and 0xFF).toByte()
                    sumSq += (v * v).toDouble()
                    i++; j += 2
                }
                try { out.write(bytes, 0, n * 2); out.flush() } catch (_: Exception) { break }
                val rms = sqrt(sumSq / n) / 32768.0
                BtState.level.postValue(min(1.0, rms * 3.0).toFloat())
            }
        } finally {
            try { record.stop() } catch (_: Exception) {}
            record.release()
        }
    }

    @SuppressLint("MissingPermission")
    private fun tryOpen(source: Int, sr: Int, bufBytes: Int): AudioRecord? {
        return try {
            val r = AudioRecord(
                source, sr,
                AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT,
                bufBytes,
            )
            if (r.state == AudioRecord.STATE_INITIALIZED) r
            else { try { r.release() } catch (_: Exception) {}; null }
        } catch (_: Throwable) { null }
    }

    // ---- Client mode -----------------------------------------------------
    @SuppressLint("MissingPermission")
    private fun startClient(address: String) {
        if (running) return
        if (!hasBtPerm(true)) {
            BtState.status.postValue("Bluetooth izni yok"); stopSelf(); return
        }
        val adapter = BluetoothAdapter.getDefaultAdapter()
        val device = try { adapter?.getRemoteDevice(address) } catch (_: Exception) { null }
        if (device == null) { BtState.status.postValue("Cihaz bulunamadı"); stopSelf(); return }
        startForeground(NOTIF_ID, buildNote("Bağlanılıyor…"), fgTypeMicrophone())
        BtState.role.postValue(ROLE_CLIENT)
        running = true
        thread = thread(name = "micky-bt-cli", isDaemon = true) {
            try {
                BtState.status.postValue("Bağlanılıyor: ${device.name ?: address}")
                adapter?.cancelDiscovery()
                // Try secure first, then insecure as fallback. Insecure works
                // even when devices weren't paired with a confirmed PIN.
                val s = try {
                    val sec = device.createRfcommSocketToServiceRecord(MICKY_BT_UUID)
                    sec.connect()
                    sec
                } catch (e: Exception) {
                    try { } catch (_: Throwable) {}
                    val insec = device.createInsecureRfcommSocketToServiceRecord(MICKY_BT_UUID)
                    insec.connect()
                    insec
                }
                socket = s
                BtState.connected.postValue(true)
                BtState.status.postValue("Bağlı: ${device.name ?: address}")
                playFrom(s.inputStream)
            } catch (e: Exception) {
                val msg = e.message ?: ""
                val hint = when {
                    msg.contains("read failed") || msg.contains("socket closed") ->
                        "Karşı telefonda Micky açık ve 'Mikrofon Ver' başlatılmış olmalı."
                    msg.contains("Connection refused") ->
                        "Karşı telefonda 'Mikrofon Ver' modu çalışmıyor."
                    msg.contains("not paired") || msg.contains("authentication") ->
                        "Telefonlar Android Ayarlar > Bluetooth'tan eşleştirilmemiş."
                    else -> ""
                }
                BtState.status.postValue("Bağlanamadı: $msg${if (hint.isNotEmpty()) " — $hint" else ""}")
            } finally {
                running = false
                BtState.connected.postValue(false)
                BtState.level.postValue(0f)
                try { socket?.close() } catch (_: Exception) {}
                socket = null
                stopForeground(STOP_FOREGROUND_REMOVE)
                BtState.status.postValue("Kapandı")
                stopSelf()
            }
        }
    }

    private fun playFrom(input: InputStream) {
        val sr = 16000
        val minBuf = AudioTrack.getMinBufferSize(
            sr, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT
        )
        val track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(sr)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build()
            )
            .setBufferSizeInBytes(maxOf(minBuf, 4096))
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()
        try {
            track.play()
            val buf = ByteArray(1024)
            val shortBuf = ShortArray(512)
            while (running && !Thread.currentThread().isInterrupted) {
                val n = try { input.read(buf) } catch (_: Exception) { -1 }
                if (n <= 0) break
                // Pack bytes into shorts for level calc (and use same byte array for write)
                var sumSq = 0.0
                var i = 0; var j = 0
                while (i + 1 < n) {
                    val s = ((buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xFF)).toShort()
                    shortBuf[j] = s
                    sumSq += (s.toInt() * s.toInt()).toDouble()
                    j++; i += 2
                }
                track.write(buf, 0, n)
                if (j > 0) {
                    val rms = sqrt(sumSq / j) / 32768.0
                    BtState.level.postValue(min(1.0, rms * 3.0).toFloat())
                }
            }
        } finally {
            try { track.stop() } catch (_: Exception) {}
            track.release()
        }
    }

    // ---- Shared ---------------------------------------------------------
    private fun stopEverything() {
        running = false
        try { serverSocket?.close() } catch (_: Exception) {}
        try { socket?.close() } catch (_: Exception) {}
        thread?.interrupt()
    }

    private fun hasBtPerm(connect: Boolean): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val p = if (connect) Manifest.permission.BLUETOOTH_CONNECT
                    else Manifest.permission.BLUETOOTH_SCAN
            return ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED
        }
        return true // legacy BT permissions are install-time
    }

    private fun buildNote(text: String): Notification {
        val stop = Intent(this, BluetoothMicService::class.java).setAction(ACTION_STOP)
        val stopPi = PendingIntent.getService(
            this, 2, stop,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val open = Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        val openPi = PendingIntent.getActivity(
            this, 0, open,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        return NotificationCompat.Builder(this, MickyApp.CHANNEL_ID)
            .setContentTitle("Micky — Bluetooth mic")
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
        stopEverything()
    }

    companion object {
        const val ACTION_START_SERVER = "com.micky.phone.BT_SERVER"
        const val ACTION_START_CLIENT = "com.micky.phone.BT_CLIENT"
        const val ACTION_STOP = "com.micky.phone.BT_STOP"
        const val EXTRA_DEVICE = "bt_device"
        const val NOTIF_ID = 202
        const val ROLE_SERVER = "server"
        const val ROLE_CLIENT = "client"
        val MICKY_BT_UUID: UUID = UUID.fromString("7b4a6fc3-1f7e-4b5d-91c4-5a7e8d4f2b61")
    }
}

object BtState {
    val status = androidx.lifecycle.MutableLiveData("Hazır")
    val connected = androidx.lifecycle.MutableLiveData(false)
    val level = androidx.lifecycle.MutableLiveData(0f)
    val role = androidx.lifecycle.MutableLiveData<String?>(null)
}
