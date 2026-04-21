package com.micky.phone

import java.io.InputStream
import java.io.OutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Wire-level framing shared with the PC side. */
object Frames {
    const val TYPE_AUDIO: Byte = 1
    const val TYPE_MUTE: Byte = 2
    const val TYPE_PING: Byte = 3
    const val TYPE_MODE: Byte = 4
    const val TYPE_NOTE: Byte = 5
    const val TYPE_FX: Byte = 6

    /** Write a frame: 1-byte type, 4-byte LE length, payload. */
    fun write(out: OutputStream, type: Byte, payload: ByteArray = ByteArray(0)) {
        val hdr = ByteBuffer.allocate(5).order(ByteOrder.LITTLE_ENDIAN)
        hdr.put(type)
        hdr.putInt(payload.size)
        synchronized(out) {
            out.write(hdr.array())
            if (payload.isNotEmpty()) out.write(payload)
            out.flush()
        }
    }

    /** Read a full frame, or null on EOF/error. */
    fun read(input: InputStream): Pair<Byte, ByteArray>? {
        val hdr = ByteArray(5)
        if (!readExact(input, hdr, 5)) return null
        val type = hdr[0]
        val len = ByteBuffer.wrap(hdr, 1, 4).order(ByteOrder.LITTLE_ENDIAN).int
        if (len < 0 || len > 1 shl 22) return null
        val payload = if (len == 0) ByteArray(0) else ByteArray(len).also {
            if (!readExact(input, it, len)) return null
        }
        return type to payload
    }

    private fun readExact(input: InputStream, buf: ByteArray, n: Int): Boolean {
        var off = 0
        while (off < n) {
            val r = input.read(buf, off, n - off)
            if (r < 0) return false
            off += r
        }
        return true
    }
}
