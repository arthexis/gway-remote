package com.arthexis.gwayremote

import com.arthexis.gwayremote.ui.shell.ModuleDrawerContent
import com.arthexis.gwayremote.ui.shell.ModuleHomePage
import com.arthexis.gwayremote.ui.shell.ModuleUpdatePage
import com.arthexis.gwayremote.features.feed.*
import com.arthexis.gwayremote.ui.components.ModulePage

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
        rule.onNodeWithText("Configuración").performScrollTo().performClick()
        rule.runOnIdle { assertEquals(ModuleRegistry.SETTINGS, selected) }
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
                    onOpenUpdate = {}
                )
            }
        }
        rule.onNodeWithText("Versión instalada: 1.2.3").assertExists()
        rule.onNodeWithText("Actualizaciones").assertExists()
        rule.onNodeWithText("App is up to date").assertExists()
        rule.onNodeWithText("Sin actualización pendiente detectada").assertDoesNotExist()
        rule.onNodeWithText("Comprobar").assertDoesNotExist()
        rule.onNodeWithText("Configuración").assertDoesNotExist()
        rule.onNodeWithText("Abre el menú", substring = true).assertDoesNotExist()
        rule.onNodeWithText("Response").assertDoesNotExist()
        rule.onNodeWithText("Filter operations").assertDoesNotExist()
    }

    @Test fun updatesCheckOncePerEntryNotRecomposition() {
        var open by mutableStateOf(false)
        var status by mutableStateOf("Ready")
        var checks = 0
        rule.setContent {
            MaterialTheme {
                if (open) ModuleUpdatePage(null, status, false, false, { checks++ }, {}, {})
                else ModuleHomePage("1.2.3", "example.test", null, status, false, { open = true })
            }
        }
        rule.onNodeWithText("Actualizaciones").performClick()
        rule.onNodeWithText("Comprobar actualizaciones").assertDoesNotExist()
        rule.runOnIdle { assertEquals(1, checks); status = "Checked" }
        rule.onNodeWithText("Checked").assertExists()
        rule.runOnIdle { assertEquals(1, checks); open = false }
        rule.onNodeWithText("Actualizaciones").performClick()
        rule.runOnIdle { assertEquals(2, checks) }
    }

    @Test fun feedRemovesWholeReadCardOnlyAfterSuccess() {
        fun item(seq: Long) = FeedItem(seq, "Article $seq", "Summary $seq", "deployment", "success",
            "2026-11-24T10:00:00Z", "2026-11-24T10:00:00Z")
        var state by mutableStateOf(FeedState(items = listOf(item(2), item(1))))
        var fail = true
        rule.setContent {
            MaterialTheme { ModulePage {
                FeedContent(state, null, false, false, null, {}, {}, {},
                    { if (!fail) state = state.mark(it) }, {}, {})
            } }
        }
        rule.onAllNodesWithText("Sin leer").assertCountEquals(0)
        rule.onNodeWithTag("feed-item-2").assertExists()
        rule.onAllNodesWithText("Marcar leído")[0].performScrollTo().performClick()
        rule.onNodeWithTag("feed-item-2").assertExists()
        rule.runOnIdle { fail = false }
        rule.onAllNodesWithText("Marcar leído")[0].performScrollTo().performClick()
        rule.onNodeWithTag("feed-item-2").assertDoesNotExist()
        rule.onNodeWithText("Summary 2").assertDoesNotExist()
        rule.onNodeWithTag("feed-item-1").assertExists()
    }
}
