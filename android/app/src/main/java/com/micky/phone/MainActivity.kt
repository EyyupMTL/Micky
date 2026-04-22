package com.micky.phone

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.micky.phone.databinding.ActivityMainBinding

const val MODE_WIFI = "wifi"
const val MODE_USB = "usb"
const val MODE_WIFI_DIRECT = "wifi_direct"
const val MODE_BLUETOOTH = "bluetooth"

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        if (savedInstanceState == null) {
            showFragment(HomeFragment())
            binding.bottomNav.selectedItemId = R.id.nav_home
        }

        binding.bottomNav.setOnItemSelectedListener { item ->
            val frag: Fragment = when (item.itemId) {
                R.id.nav_home -> HomeFragment()
                R.id.nav_bluetooth -> BluetoothFragment()
                R.id.nav_settings -> SettingsFragment()
                else -> return@setOnItemSelectedListener false
            }
            showFragment(frag)
            true
        }

        intent?.data?.let { handleUri(it) }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        intent.data?.let { handleUri(it) }
    }

    private fun handleUri(uri: Uri) {
        if (uri.scheme != "micky") return
        val host = uri.host ?: return
        val port = if (uri.port > 0) uri.port else 8125
        val mode = uri.getQueryParameter("mode") ?: MODE_WIFI
        val safeMode = when (mode) {
            MODE_USB, MODE_WIFI_DIRECT, MODE_BLUETOOTH, MODE_WIFI -> mode
            else -> MODE_WIFI
        }
        Prefs.get(this).edit()
            .putString(Prefs.KEY_HOST, host)
            .putString(Prefs.KEY_PORT, port.toString())
            .putString(Prefs.KEY_MODE, safeMode)
            .apply()
        // refresh current fragment
        showFragment(
            if (binding.bottomNav.selectedItemId == R.id.nav_settings) SettingsFragment()
            else HomeFragment()
        )
    }

    private fun showFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.navHost, fragment)
            .commit()
    }
}
