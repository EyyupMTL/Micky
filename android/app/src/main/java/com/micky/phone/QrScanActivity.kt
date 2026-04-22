package com.micky.phone

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.google.zxing.BarcodeFormat
import com.google.zxing.ResultPoint
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory

/**
 * Portrait QR scanner — owns its own [DecoratedBarcodeView] so orientation
 * always matches the preview (the root cause the old ScanContract wrapper
 * failed on this device).
 */
class QrScanActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_RESULT = "scan_result"
    }

    private lateinit var view: DecoratedBarcodeView
    private var consumed = false

    private val cameraPerm = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) startScan()
        else {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
        setContentView(R.layout.activity_qr_scan)
        view = findViewById(R.id.barcodeView)
        findViewById<android.view.View>(R.id.cancelBtn).setOnClickListener {
            setResult(Activity.RESULT_CANCELED)
            finish()
        }

        view.decoderFactory = DefaultDecoderFactory(listOf(BarcodeFormat.QR_CODE))
        view.setStatusText("")

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED) {
            cameraPerm.launch(Manifest.permission.CAMERA)
        } else {
            startScan()
        }
    }

    private fun startScan() {
        view.decodeContinuous(object : BarcodeCallback {
            override fun barcodeResult(result: BarcodeResult?) {
                if (consumed || result?.text.isNullOrBlank()) return
                consumed = true
                val data = Intent().putExtra(EXTRA_RESULT, result?.text)
                setResult(Activity.RESULT_OK, data)
                finish()
            }
            override fun possibleResultPoints(resultPoints: MutableList<ResultPoint>?) {}
        })
    }

    override fun onResume() {
        super.onResume()
        if (::view.isInitialized) view.resume()
    }

    override fun onPause() {
        super.onPause()
        if (::view.isInitialized) view.pause()
    }

    override fun onKeyDown(keyCode: Int, event: android.view.KeyEvent?): Boolean {
        return view.onKeyDown(keyCode, event) || super.onKeyDown(keyCode, event)
    }
}
