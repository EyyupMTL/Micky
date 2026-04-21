package com.micky.phone

import androidx.lifecycle.MutableLiveData

/** Shared observable state between the streaming service and UI. */
object State {
    val status = MutableLiveData("Hazır")
    val connected = MutableLiveData(false)
    val muted = MutableLiveData(false)
    val level = MutableLiveData(0f)
    val serverMode = MutableLiveData<String?>(null)
    val mismatch = MutableLiveData<String?>(null)
    val fx = MutableLiveData("normal")
}
