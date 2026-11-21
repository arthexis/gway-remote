package com.arthexis.gwayremote

import com.arthexis.gwayremote.ui.shell.ModuleDrawerContent
import com.arthexis.gwayremote.ui.shell.ModuleHomePage

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ModuleNavigationComposeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun drawerSelectsAnEntireModuleWithoutOpeningASecondPanel() {
        var selected by mutableStateOf(ModuleRegistry.HOME)
        rule.setContent {
            MaterialTheme {
                ModuleDrawerContent(selectedId = selected, updateAvailable = false,
                    onSelect = { selected = it })
            }
        }
        rule.onNodeWithText("Inicio").assertExists()
        rule.onNodeWithText("System").performClick()
        rule.runOnIdle { assertEquals("system", selected) }
        rule.onNodeWithText("Filter operations").assertDoesNotExist()
        rule.onNodeWithText("More tools and settings").assertDoesNotExist()
    }

    @Test fun homeHasOnlyAppInformationAndUpdateEntry() {
        rule.setContent {
            MaterialTheme {
                ModuleHomePage(
                    installedVersion = "1.2.3",
                    configuredEndpoint = "remote.arthexis.com",
                    availableUpdate = null,
                    updateStatus = "App is up to date",
                    updating = false,
                    onOpenUpdate = {}, onCheckUpdate = {}, onOpenSettings = {}
                )
            }
        }
        rule.onNodeWithText("Versión instalada: 1.2.3").assertExists()
        rule.onNodeWithText("Actualizaciones").assertExists()
        rule.onNodeWithText("Response").assertDoesNotExist()
        rule.onNodeWithText("Filter operations").assertDoesNotExist()
    }
}
