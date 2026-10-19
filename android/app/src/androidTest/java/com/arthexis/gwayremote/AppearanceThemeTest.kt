package com.arthexis.gwayremote

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertExists
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.graphics.Color
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Theme assertions use production Compose components and no network connection. */
class AppearanceThemeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun switchingAppearanceUpdatesMaterialColorsWithoutRecreatingScreen() {
        var selection by mutableStateOf(AppearanceMode.SYSTEM)
        var observedColor = Color.Unspecified
        rule.setContent {
            GwayRemoteTheme(darkTheme = selection.isDark(false)) {
                observedColor = MaterialTheme.colorScheme.background
                androidx.compose.material3.Button(onClick = { selection = AppearanceMode.DARK }) {
                    androidx.compose.material3.Text("Dark")
                }
                androidx.compose.material3.Text("Theme content")
            }
        }
        var light = Color.Unspecified
        rule.runOnIdle { light = observedColor }
        rule.onNodeWithText("Dark").performClick()
        rule.runOnIdle {
            assertEquals(AppearanceMode.DARK, selection)
            assertNotEquals(light, observedColor)
        }
        rule.onNodeWithText("Theme content").assertExists()
    }

    @Test fun updateIndicatorRemainsPresentInBothModes() {
        var dark by mutableStateOf(false)
        rule.setContent {
            GwayRemoteTheme(darkTheme = dark) {
                androidx.compose.foundation.layout.Column {
                    FeatureButton(PaletteAction("app-update", "App update", "update", {}, attention = true))
                    androidx.compose.material3.Button(onClick = { dark = !dark }) {
                        androidx.compose.material3.Text("Toggle theme")
                    }
                }
            }
        }
        rule.onNodeWithContentDescription("Update available").assertExists()
        rule.onNodeWithText("Toggle theme").performClick()
        rule.onNodeWithContentDescription("Update available").assertExists()
    }
}
