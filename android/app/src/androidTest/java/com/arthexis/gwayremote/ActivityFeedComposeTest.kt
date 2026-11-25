package com.arthexis.gwayremote

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.arthexis.gwayremote.features.feed.*
import com.arthexis.gwayremote.ui.components.ModulePage
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ActivityFeedComposeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun filtersOfflineReadAndNavigation() {
        var state by mutableStateOf(FeedState(items = listOf(
            FeedItem(2, "Deploy completed", "Example", "deployment", "success", "2026-11-24T10:00:00Z", "2026-11-24T10:00:00Z"),
            FeedItem(1, "Node connected", "Example", "fleet", "info", "2026-11-24T09:00:00Z", "2026-11-24T09:00:00Z")
        ), next = 1, more = true))
        var category by mutableStateOf<String?>(null)
        var opened = ""
        var more = 0
        rule.setContent {
            MaterialTheme {
                ModulePage {
                    FeedContent(state, category, false, true, null, { category = it }, {},
                        { more++ }, { state = state.mark(it) }, { opened = it }, {})
                }
            }
        }
        rule.onNodeWithText("Historial offline").assertExists()
        rule.onNodeWithText("deployment", substring = false).performClick()
        rule.onNodeWithText("Deploy completed").assertExists()
        rule.onNodeWithText("Node connected").assertDoesNotExist()
        rule.onNodeWithText("Marcar leído").performScrollTo().performClick()
        rule.onNodeWithText("Sin leer").assertDoesNotExist()
        rule.onNodeWithTag("feed-item-2").assertDoesNotExist()
        rule.onNodeWithText("Deploy completed").assertDoesNotExist()
        rule.onNodeWithText("Todos").performClick()
        rule.onNodeWithText("Node connected").assertExists()
        rule.onNodeWithText("Cargar anteriores").performScrollTo().performClick()
        rule.runOnIdle { assertEquals("", opened); assertEquals(1, more) }
    }
}
