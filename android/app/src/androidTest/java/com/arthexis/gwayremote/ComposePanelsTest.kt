package com.arthexis.gwayremote

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Compose parity for current native modules; retired tasks/simulator removed. */
class ComposePanelsTest {
    @get:Rule val rule = createComposeRule()

    @Test fun csmsInspectionSelectsViewWithoutDispatchUntilConfirm() {
        val inspected = mutableListOf<String>()
        var selected by mutableStateOf<String?>(null)
        rule.setContent {
            MaterialTheme {
                CsmsUnifiedPanel(
                    OperationPanel("csms"),
                    onRefresh = {}, onInspect = { inspected.add(it) },
                    selectedView = selected, onSelectView = { selected = it }
                )
            }
        }
        rule.onNodeWithText("Inspect: status", substring = true).performClick()
        rule.onNodeWithText("events", useUnmergedTree = true).performClick()
        rule.runOnIdle {
            assertEquals("events", selected)
            assertTrue(inspected.isEmpty())
        }
        rule.onNodeWithText("Inspect events").performClick()
        rule.runOnIdle { assertEquals(listOf("events"), inspected) }
    }

    @Test fun switchingNotificationTabsNeverAutoRunsActions() {
        val inputs = mutableListOf<String>()
        val executions = mutableListOf<String>()
        rule.setContent {
            MaterialTheme {
                ModuleNotificationsContent(
                    lcd = ModuleOperationViewModel.NotificationRun(),
                    sound = ModuleOperationViewModel.NotificationRun(),
                    motifs = listOf("notice"),
                    onInput = { _, key, _ -> inputs.add(key) },
                    onExecute = { kind, _ -> executions.add(kind) }
                )
            }
        }
        rule.onNodeWithText("LCD message").performClick()
        rule.runOnIdle { assertTrue(executions.isEmpty()) }
        rule.onNodeWithText("Sound").performClick()
        rule.runOnIdle { assertTrue(executions.isEmpty()) }
    }

    @Test fun systemChecksDoNotRequireLegacyPanelChrome() {
        rule.setContent {
            MaterialTheme {
                ModuleSystemContent(
                    api = ModuleOperationViewModel.SystemCheck(output = """{"result":{"healthy":true}}"""),
                    status = ModuleOperationViewModel.SystemCheck(),
                    refresh = {}
                )
            }
        }
        rule.onNodeWithText("API Health").performClick()
        rule.onNodeWithText("API health").assertExists()
        rule.onNodeWithText("Close panel").assertDoesNotExist()
    }
}
