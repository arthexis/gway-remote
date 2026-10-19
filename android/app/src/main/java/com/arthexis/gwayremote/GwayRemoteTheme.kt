package com.arthexis.gwayremote

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

/**
 * App-owned Material 3 color schemes.
 *
 * D1 defines the theme independently of Activity and Android window styling.
 * D2 will install it at the application root; D3 will add a persisted
 * System/Light/Dark preference.
 */
@Composable
fun GwayRemoteTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) darkColorScheme() else lightColorScheme(),
        content = content
    )
}
