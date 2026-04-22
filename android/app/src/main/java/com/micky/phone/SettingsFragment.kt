package com.micky.phone

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import com.google.android.material.snackbar.Snackbar
import com.micky.phone.databinding.FragmentSettingsBinding

class SettingsFragment : Fragment() {

    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!

    private val qrLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            val raw = result.data?.getStringExtra(QrScanActivity.EXTRA_RESULT)
            if (!raw.isNullOrBlank()) applyUri(raw)
        }
    }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentSettingsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        val prefs = Prefs.get(requireContext())
        binding.hostInput.setText(prefs.getString(Prefs.KEY_HOST, ""))
        binding.portInput.setText(prefs.getString(Prefs.KEY_PORT, "8125"))

        binding.hostInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                prefs.edit().putString(Prefs.KEY_HOST, s?.toString().orEmpty()).apply()
            }
        })
        binding.portInput.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                prefs.edit().putString(Prefs.KEY_PORT, s?.toString().orEmpty()).apply()
            }
        })

        binding.scanBtn.setOnClickListener { launchScanner() }
    }

    private fun launchScanner() {
        qrLauncher.launch(Intent(requireContext(), QrScanActivity::class.java))
    }

    private fun applyUri(raw: String) {
        val uri = runCatching { Uri.parse(raw) }.getOrNull()
        if (uri == null || uri.scheme != "micky") {
            snack("Geçersiz QR: $raw")
            return
        }
        val host = uri.host ?: return
        val port = if (uri.port > 0) uri.port else 8125
        val mode = uri.getQueryParameter("mode") ?: MODE_WIFI
        val safeMode = when (mode) {
            MODE_USB, MODE_WIFI_DIRECT, MODE_BLUETOOTH, MODE_WIFI -> mode
            else -> MODE_WIFI
        }
        val prefs = Prefs.get(requireContext())
        prefs.edit()
            .putString(Prefs.KEY_HOST, host)
            .putString(Prefs.KEY_PORT, port.toString())
            .putString(Prefs.KEY_MODE, safeMode)
            .apply()
        binding.hostInput.setText(host)
        binding.portInput.setText(port.toString())
        snack("Eşleştirildi: $host:$port ($safeMode)")
    }

    private fun snack(msg: String) {
        Snackbar.make(binding.root, msg, Snackbar.LENGTH_SHORT).show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
