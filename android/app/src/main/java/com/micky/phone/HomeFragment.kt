package com.micky.phone

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.google.android.material.chip.Chip
import com.google.android.material.snackbar.Snackbar
import com.micky.phone.databinding.FragmentHomeBinding

class HomeFragment : Fragment() {

    private var _binding: FragmentHomeBinding? = null
    private val binding get() = _binding!!

    private val requestPerms = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* no-op */ }

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentHomeBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        applyModeToChips(currentMode())
        refreshTargetText()

        binding.modeChips.setOnCheckedStateChangeListener { _, ids ->
            val id = ids.firstOrNull() ?: return@setOnCheckedStateChangeListener
            val mode = when (id) {
                R.id.chipWifi -> MODE_WIFI
                R.id.chipUsb -> MODE_USB
                R.id.chipDirect -> MODE_WIFI_DIRECT
                R.id.chipBt -> MODE_BLUETOOTH
                else -> MODE_WIFI
            }
            Prefs.get(requireContext()).edit().putString(Prefs.KEY_MODE, mode).apply()
            if (mode == MODE_USB) {
                Prefs.get(requireContext()).edit().putString(Prefs.KEY_HOST, "127.0.0.1").apply()
            }
            refreshTargetText()
        }

        binding.micOrb.setOnClickListener { toggleMute() }
        binding.connectBtn.setOnClickListener {
            if (State.connected.value == true) stopStream() else startStream()
        }

        // Gain slider — local prefs + push to PC while user drags
        val savedGain = Prefs.get(requireContext())
            .getString(Prefs.KEY_GAIN, "1.0")?.toFloatOrNull() ?: 1.0f
        binding.gainSlider.value = savedGain.coerceIn(0f, 3f)
        binding.gainValue.text = String.format(java.util.Locale.US, "%.2f×", savedGain)
        State.gain.value = savedGain
        binding.gainSlider.addOnChangeListener { _, value, fromUser ->
            binding.gainValue.text = String.format(java.util.Locale.US, "%.2f×", value)
            if (fromUser) {
                State.gain.value = value
                Prefs.get(requireContext()).edit()
                    .putString(Prefs.KEY_GAIN, value.toString())
                    .apply()
                val intent = Intent(requireContext(), MicStreamService::class.java).apply {
                    action = MicStreamService.ACTION_GAIN
                    putExtra(MicStreamService.EXTRA_GAIN, value)
                }
                requireContext().startService(intent)
            }
        }

        // Initialise FX from prefs so it survives app restarts
        val savedFx = Prefs.get(requireContext()).getString(Prefs.KEY_FX, "normal") ?: "normal"
        if (State.fx.value != savedFx) State.fx.value = savedFx

        // Build FX chips dynamically so IDs stay stable to selection lookup by tag
        val currentFx = State.fx.value ?: "normal"
        Fx.presets.forEach { (id, label) ->
            val chip = Chip(requireContext()).apply {
                text = label
                tag = id
                isCheckable = true
                isCheckedIconVisible = true
                setChipBackgroundColorResource(R.color.panel_light)
                setTextColor(resources.getColor(R.color.text, null))
                setChipStrokeColorResource(R.color.border)
                chipStrokeWidth = 1f
                isChecked = (id == currentFx)
                setOnClickListener {
                    if (isChecked) selectFx(id)
                }
            }
            binding.fxChips.addView(chip)
        }

        State.status.observe(viewLifecycleOwner) { binding.statusText.text = (it ?: "").uppercase() }
        State.connected.observe(viewLifecycleOwner) { on ->
            binding.micOrb.connected = on == true
            if (on == true) {
                binding.connectBtn.text = "Yayını durdur"
                binding.connectBtn.setIconResource(R.drawable.ic_stop)
                binding.bigStatusText.text = if (State.muted.value == true) "Sessize alındı" else "Yayınlanıyor"
            } else {
                binding.connectBtn.text = "Yayını başlat"
                binding.connectBtn.setIconResource(R.drawable.ic_mic)
                binding.bigStatusText.text = "Yayın kapalı"
                binding.vu.setLevel(0f)
                binding.micOrb.setLevel(0f)
            }
        }
        State.level.observe(viewLifecycleOwner) {
            binding.vu.setLevel(it ?: 0f)
            binding.micOrb.setLevel(it ?: 0f)
        }
        State.muted.observe(viewLifecycleOwner) { m ->
            binding.micOrb.muted = m == true
            if (State.connected.value == true) {
                binding.bigStatusText.text = if (m == true) "Sessize alındı" else "Yayınlanıyor"
            }
            binding.orbHint.text = if (m == true) "sesi açmak için dokun" else "sessize almak için dokun"
        }
        State.fx.observe(viewLifecycleOwner) { preset ->
            // Reflect FX state in chip selection without re-triggering
            for (i in 0 until binding.fxChips.childCount) {
                val c = binding.fxChips.getChildAt(i) as? Chip ?: continue
                val shouldCheck = c.tag == preset
                if (c.isChecked != shouldCheck) c.isChecked = shouldCheck
            }
        }
        State.gain.observe(viewLifecycleOwner) { value ->
            val v = value ?: 1.0f
            // Avoid slider feedback loop: only update if meaningfully different
            if (kotlin.math.abs(binding.gainSlider.value - v) > 0.01f) {
                binding.gainSlider.value = v.coerceIn(0f, 3f)
            }
            binding.gainValue.text = String.format(java.util.Locale.US, "%.2f×", v)
        }
        State.mismatch.observe(viewLifecycleOwner) { serverMode ->
            if (serverMode == null) {
                binding.mismatchBanner.visibility = View.GONE
            } else {
                val pretty = mapOf(
                    "wifi" to "Wi-Fi", "usb" to "USB",
                    "wifi_direct" to "Wi-Fi Direct", "bluetooth" to "Bluetooth"
                )
                val mine = pretty[currentMode()] ?: currentMode()
                val server = pretty[serverMode] ?: serverMode
                binding.mismatchBanner.text = "⚠ Mod uyuşmuyor — PC: $server · Telefon: $mine"
                binding.mismatchBanner.visibility = View.VISIBLE
            }
        }

        val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms += Manifest.permission.POST_NOTIFICATIONS
        }
        val missing = perms.filter {
            ContextCompat.checkSelfPermission(requireContext(), it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) requestPerms.launch(missing.toTypedArray())
    }

    override fun onResume() {
        super.onResume()
        applyModeToChips(currentMode())
        refreshTargetText()
    }

    private fun currentMode(): String =
        Prefs.get(requireContext()).getString(Prefs.KEY_MODE, MODE_WIFI) ?: MODE_WIFI

    private fun applyModeToChips(mode: String) {
        val id = when (mode) {
            MODE_USB -> R.id.chipUsb
            MODE_WIFI_DIRECT -> R.id.chipDirect
            MODE_BLUETOOTH -> R.id.chipBt
            else -> R.id.chipWifi
        }
        binding.modeChips.check(id)
        binding.connectBtn.isEnabled = mode != MODE_BLUETOOTH
    }

    private fun refreshTargetText() {
        val prefs = Prefs.get(requireContext())
        val host = prefs.getString(Prefs.KEY_HOST, "") ?: ""
        val port = prefs.getString(Prefs.KEY_PORT, "8125") ?: "8125"
        binding.targetText.text =
            if (host.isBlank()) "Hedef: Ayarlar sekmesinden IP gir veya QR tara"
            else "→ $host:$port"
    }

    private fun startStream() {
        val prefs = Prefs.get(requireContext())
        val host = prefs.getString(Prefs.KEY_HOST, "")?.trim().orEmpty()
        val port = prefs.getString(Prefs.KEY_PORT, "8125")?.toIntOrNull() ?: 8125
        val mode = currentMode()
        if (host.isEmpty()) {
            snack("Önce Ayarlar'dan IP gir veya QR tara")
            return
        }
        if (ContextCompat.checkSelfPermission(requireContext(), Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED) {
            requestPerms.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
            return
        }
        val mic = prefs.getString(Prefs.KEY_MIC, Prefs.MIC_AUTO) ?: Prefs.MIC_AUTO
        val intent = Intent(requireContext(), MicStreamService::class.java).apply {
            action = MicStreamService.ACTION_START
            putExtra(MicStreamService.EXTRA_HOST, host)
            putExtra(MicStreamService.EXTRA_PORT, port)
            putExtra(MicStreamService.EXTRA_MODE, mode)
            putExtra(MicStreamService.EXTRA_MIC, mic)
        }
        ContextCompat.startForegroundService(requireContext(), intent)
    }

    private fun stopStream() {
        val intent = Intent(requireContext(), MicStreamService::class.java)
            .setAction(MicStreamService.ACTION_STOP)
        requireContext().startService(intent)
    }

    private fun selectFx(presetId: String) {
        State.fx.value = presetId
        Prefs.get(requireContext()).edit().putString(Prefs.KEY_FX, presetId).apply()
        val intent = Intent(requireContext(), MicStreamService::class.java).apply {
            action = MicStreamService.ACTION_FX
            putExtra(MicStreamService.EXTRA_FX, presetId)
        }
        requireContext().startService(intent)
    }

    private fun toggleMute() {
        if (State.connected.value != true) {
            // Not connected — tapping the orb starts a stream
            startStream()
            return
        }
        val newMuted = State.muted.value != true
        State.muted.value = newMuted
        val intent = Intent(requireContext(), MicStreamService::class.java).apply {
            action = MicStreamService.ACTION_MUTE
            putExtra(MicStreamService.EXTRA_MUTED, newMuted)
        }
        requireContext().startService(intent)
    }

    private fun snack(msg: String) {
        Snackbar.make(binding.root, msg, Snackbar.LENGTH_SHORT).show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}
