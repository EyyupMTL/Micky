package com.micky.phone

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import com.google.android.material.button.MaterialButton
import com.google.android.material.snackbar.Snackbar
import com.micky.phone.databinding.FragmentBtBinding

class BluetoothFragment : Fragment() {
    private var _b: FragmentBtBinding? = null
    private val b get() = _b!!

    private var role: String = BluetoothMicService.ROLE_SERVER
    private var pickedDeviceAddress: String? = null

    private val requestPerms = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grants ->
        if (grants.values.all { it }) kickOff()
        else snack("İzin verilmedi")
    }

    override fun onCreateView(i: LayoutInflater, c: ViewGroup?, s: Bundle?): View {
        _b = FragmentBtBinding.inflate(i, c, false)
        return b.root
    }

    override fun onViewCreated(view: View, s: Bundle?) {
        super.onViewCreated(view, s)
        applyRoleToUi(role)

        b.roleChips.setOnCheckedStateChangeListener { _, ids ->
            val id = ids.firstOrNull() ?: return@setOnCheckedStateChangeListener
            role = if (id == R.id.chipClient) BluetoothMicService.ROLE_CLIENT
                    else BluetoothMicService.ROLE_SERVER
            applyRoleToUi(role)
        }
        b.refreshBtn.setOnClickListener { refreshPairedDevices() }
        b.actionBtn.setOnClickListener { onActionClicked() }
        b.openBtSettingsBtn.setOnClickListener {
            try {
                startActivity(Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS))
            } catch (_: Exception) {
                snack("Bluetooth ayarları açılamadı")
            }
        }

        BtState.status.observe(viewLifecycleOwner) { b.btStatus.text = it ?: "" }
        BtState.connected.observe(viewLifecycleOwner) { connected ->
            b.actionBtn.text = when {
                connected == true -> "Durdur"
                role == BluetoothMicService.ROLE_SERVER -> "Mikrofonu paylaşmaya başla"
                else -> "Seçili cihaza bağlan"
            }
            b.actionBtn.setIconResource(if (connected == true) R.drawable.ic_stop else R.drawable.ic_mic)
            b.actionBtn.backgroundTintList = android.content.res.ColorStateList.valueOf(
                if (connected == true) 0xFFFF6B6B.toInt() else 0xFF8AFFC1.toInt()
            )
        }
        BtState.level.observe(viewLifecycleOwner) { b.btVu.setLevel(it ?: 0f) }
    }

    private fun applyRoleToUi(r: String) {
        if (r == BluetoothMicService.ROLE_CLIENT) {
            b.devicesCard.visibility = View.VISIBLE
            b.roleHint.text =
                "1) Önce iki telefonu Bluetooth ayarlarından eşleştir.\n" +
                "2) Karşı telefondaki Micky'de 'Mikrofon Ver' başlat.\n" +
                "3) Aşağıda eşleşmiş cihazlardan onu seç → 'Bağlan'.\n" +
                "Bu telefon sesi HOPARLÖRDEN çalar; video çekerken kendi mikrofonu hoparlörü kaydeder."
            refreshPairedDevices()
        } else {
            b.devicesCard.visibility = View.GONE
            b.roleHint.text =
                "1) Önce iki telefonu Bluetooth ayarlarından eşleştir.\n" +
                "2) 'Mikrofonu paylaşmaya başla' → bu telefon dinlemeye geçer.\n" +
                "3) Karşı telefonda 'Mikrofon Al' → bu cihaza bağlansın."
        }
    }

    @SuppressLint("MissingPermission")
    private fun refreshPairedDevices() {
        if (!ensurePerms(connect = true, scan = false)) return
        val adapter = BluetoothAdapter.getDefaultAdapter()
        if (adapter == null) { snack("Bu cihazda Bluetooth yok"); return }
        if (!adapter.isEnabled) { snack("Bluetooth kapalı — aç ve tekrar dene"); return }
        b.deviceList.removeAllViews()
        val bonded = adapter.bondedDevices ?: emptySet()
        if (bonded.isEmpty()) {
            val tv = TextView(requireContext()).apply {
                text = "Eşleşmiş cihaz yok. Android Ayarlar'dan eşleştir."
                setTextColor(resources.getColor(R.color.text_dim, null))
                textSize = 13f
                setPadding(0, 8, 0, 8)
            }
            b.deviceList.addView(tv)
            return
        }
        bonded.forEach { d ->
            val btn = MaterialButton(
                requireContext(), null,
                com.google.android.material.R.attr.materialButtonOutlinedStyle,
            ).apply {
                text = "${d.name ?: "?"}   ${d.address}"
                textSize = 13f
                isAllCaps = false
                setTextColor(resources.getColor(R.color.text, null))
                cornerRadius = 12
                strokeColor = resources.getColorStateList(R.color.border, null)
                layoutParams = ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
                )
                setOnClickListener {
                    pickedDeviceAddress = d.address
                    for (i in 0 until b.deviceList.childCount) {
                        (b.deviceList.getChildAt(i) as? MaterialButton)?.isChecked =
                            (b.deviceList.getChildAt(i) === this)
                    }
                    snack("${d.name ?: d.address} seçildi")
                }
            }
            b.deviceList.addView(btn)
        }
    }

    private fun onActionClicked() {
        val connected = BtState.connected.value == true
        if (connected) {
            val i = Intent(requireContext(), BluetoothMicService::class.java)
                .setAction(BluetoothMicService.ACTION_STOP)
            requireContext().startService(i)
            return
        }
        if (!ensurePerms(connect = true, scan = role == BluetoothMicService.ROLE_SERVER)) return
        if (role == BluetoothMicService.ROLE_CLIENT) {
            val addr = pickedDeviceAddress
            if (addr == null) { snack("Önce bir eşleşmiş cihaz seç"); return }
            val i = Intent(requireContext(), BluetoothMicService::class.java).apply {
                action = BluetoothMicService.ACTION_START_CLIENT
                putExtra(BluetoothMicService.EXTRA_DEVICE, addr)
            }
            ContextCompat.startForegroundService(requireContext(), i)
        } else {
            // Optionally make the device discoverable so the other phone can
            // pair with it if it isn't already.
            try {
                val discover = Intent(BluetoothAdapter.ACTION_REQUEST_DISCOVERABLE).apply {
                    putExtra(BluetoothAdapter.EXTRA_DISCOVERABLE_DURATION, 120)
                }
                startActivity(discover)
            } catch (_: Exception) { /* not critical */ }
            val i = Intent(requireContext(), BluetoothMicService::class.java)
                .setAction(BluetoothMicService.ACTION_START_SERVER)
            ContextCompat.startForegroundService(requireContext(), i)
        }
    }

    private fun kickOff() = onActionClicked()

    private fun ensurePerms(connect: Boolean, scan: Boolean): Boolean {
        val need = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (connect && ContextCompat.checkSelfPermission(
                    requireContext(), Manifest.permission.BLUETOOTH_CONNECT
                ) != PackageManager.PERMISSION_GRANTED) need += Manifest.permission.BLUETOOTH_CONNECT
            if (scan && ContextCompat.checkSelfPermission(
                    requireContext(), Manifest.permission.BLUETOOTH_SCAN
                ) != PackageManager.PERMISSION_GRANTED) need += Manifest.permission.BLUETOOTH_SCAN
            if (role == BluetoothMicService.ROLE_SERVER && ContextCompat.checkSelfPermission(
                    requireContext(), Manifest.permission.BLUETOOTH_ADVERTISE
                ) != PackageManager.PERMISSION_GRANTED) need += Manifest.permission.BLUETOOTH_ADVERTISE
        }
        if (role == BluetoothMicService.ROLE_SERVER &&
            ContextCompat.checkSelfPermission(
                requireContext(), Manifest.permission.RECORD_AUDIO
            ) != PackageManager.PERMISSION_GRANTED) need += Manifest.permission.RECORD_AUDIO
        if (need.isEmpty()) return true
        requestPerms.launch(need.toTypedArray())
        return false
    }

    private fun snack(msg: String) {
        Snackbar.make(b.root, msg, Snackbar.LENGTH_SHORT).show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _b = null
    }
}
