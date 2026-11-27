package com.arthexis.gwayremote

import com.arthexis.gwayremote.ui.shell.ModuleSettingsPage
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Hermetic UI interactions: no credentials are persisted or sent over the network. */
class ModuleSettingsInteractionTest {
    @get:Rule val rule = createComposeRule()

    @Test fun settingsAppearanceAndSaveInvokeOnlyTheirExplicitCallbacks() {
        var appearance by mutableStateOf(AppearanceMode.SYSTEM)
        var endpoint by mutableStateOf("https://remote.arthexis.com")
        var token by mutableStateOf("test-only-secret")
        var saves = 0
        rule.setContent {
            MaterialTheme {
                ModuleSettingsPage(
                    settings = CompanionSettingsState.initial(endpoint, token),
                    appearance = appearance,
                    onAppearanceChange = { appearance = it },
                    onEndpointChange = { endpoint = it },
                    onTokenChange = { token = it },
                    onSave = { saves++ },
                    feedback = ""
                )
            }
        }
        rule.runOnIdle { assertEquals(0, saves) }
        rule.onNodeWithText(AppearanceMode.DARK.label).performClick()
        rule.runOnIdle {
            assertEquals(AppearanceMode.DARK, appearance)
            assertEquals(0, saves)
        }
        rule.onNodeWithText("HTTPS endpoint").assertExists()
        rule.onNodeWithText("Bearer token").assertExists()
        rule.onNodeWithText("Guardar configuración").performClick()
        rule.runOnIdle { assertEquals(1, saves) }
        rule.onNodeWithText("test-only-secret").assertDoesNotExist()
    }
}
