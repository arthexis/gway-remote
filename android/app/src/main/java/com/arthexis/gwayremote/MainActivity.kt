package com.arthexis.gwayremote

import com.arthexis.gwayremote.ui.shell.CompanionScreen

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.graphics.toArgb
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsControllerCompat

/** Android entry point only; module navigation and controllers live elsewhere. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        window.setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE)
        UpdateNotifications.createChannel(this)
        UpdateNotifications.schedule(this)
        val store = SecretStore(this)
        setContent {
            val appearancePrefs = remember { getSharedPreferences("appearance", Context.MODE_PRIVATE) }
            var appearance by remember { mutableStateOf(AppearanceMode.fromStored(appearancePrefs.getString("mode", null))) }
            val dark = appearance.isDark(isSystemInDarkTheme())
            GwayRemoteTheme(darkTheme = dark) {
                val surfaceColor = MaterialTheme.colorScheme.background.toArgb()
                SideEffect {
                    window.statusBarColor = surfaceColor
                    window.navigationBarColor = surfaceColor
                    WindowInsetsControllerCompat(window, window.decorView).apply {
                        isAppearanceLightStatusBars = !dark
                        isAppearanceLightNavigationBars = !dark
                    }
                }
                CompanionScreen(store, appearance) { next ->
                    appearance = next
                    appearancePrefs.edit().putString("mode", next.name).apply()
                }
            }
        }
    }
}

