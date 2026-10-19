package com.arthexis.gwayremote

import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Instrumented tests exercise real Compose elements without contacting the appliance. */
class ComposePanelsTest {
    @get:Rule val rule = createComposeRule()

    @Test fun paletteRowsDoNotOverlapAtPhoneWidthAndRemainTouchAccessible() {
        rule.setContent {
            MaterialTheme {
                BoxWithConstraints {
                    // The actual responsive layout code and FeatureButton implementation.
                    val actions = FeatureRegistry.features
                        .filter { it.kind == FeatureKind.OPERATION }
                        .take(4)
                        .map { PaletteAction(it.id, it.label, it.icon, {}) }
                    PaletteActionRows(actions, paletteColumns(maxWidth.value))
                }
            }
        }
        val labels = FeatureRegistry.features.filter { it.kind == FeatureKind.OPERATION }
            .take(4).map { it.label }
        val rects = labels.map { label ->
            rule.onNodeWithContentDescription(label).assertExists().getUnclippedBoundsInRoot()
        }
        for (i in rects.indices) {
            assertTrue("Touch target too short: ${labels[i]}", rects[i].height >= 48.dp)
            for (j in i + 1 until rects.size) {
                val overlapX = rects[i].left < rects[j].right && rects[j].left < rects[i].right
                val overlapY = rects[i].top < rects[j].bottom && rects[j].top < rects[i].bottom
                assertFalse("Palette actions overlap: ${labels[i]} / ${labels[j]}", overlapX && overlapY)
            }
        }
    }

    @Test fun csmsSelectorKeepsInspectionInsideUnifiedCard() {
        var inspected: String? = null
        var selected by mutableStateOf<String?>(null)
        rule.setContent {
            val panel = OperationPanelState().open("csms").state.panels.single()
            MaterialTheme {
                CsmsUnifiedPanel(panel, onRefresh = {}, onInspect = { inspected = it },
                    selectedView = selected, onSelectView = { selected = it })
            }
        }
        rule.onNodeWithText("Inspect: status", substring = true).performClick()
        rule.onNodeWithText("events", useUnmergedTree = true).performClick()
        rule.onNodeWithText("Inspect events").performClick()
        rule.runOnIdle { assertEquals("events", inspected) }
    }

    @Test fun tasksShowHistoryAndDetailInSameCard() {
        val id = "8fc71471-92b8-4202-bda1-3dc4fe348402"
        val history = JSONObject().put("result", JSONObject().put("tasks",
            org.json.JSONArray().put(JSONObject().put("task",
                JSONObject().put("id", id).put("state", "done"))))).toString()
        var selected by mutableStateOf<String?>(null)
        rule.setContent {
            val raw = OperationPanelState().open("tasks").state
            val panel = raw.start("tasks").let { started ->
                started.complete("tasks", started.panels.single().revision, history)
            }.panels.single()
            MaterialTheme {
                TasksUnifiedPanel(panel, detail = null, detailLoading = false,
                    detailError = null, selection = selected, inspect = { selected = it })
            }
        }
        rule.onNodeWithText("Inspect details").performClick()
        rule.onNodeWithText("Selected task: 8fc71471").assertExists()
        rule.onNodeWithText("Task 8fc71471", substring = true).assertExists()
    }

    @Test fun simulatorReadTabsDoNotDispatchMutatingCommands() {
        val reads = mutableListOf<String>()
        val commands = mutableListOf<String>()
        rule.setContent {
            val panel = OperationPanelState().open("simulator").state.panels.single()
            MaterialTheme {
                SimulatorUnifiedPanel(panel, "unknown", onInput = { _, _, _ -> },
                    onRead = { command, _ -> reads.add(command) },
                    onCommand = { command, _ -> commands.add(command) })
            }
        }
        rule.onNodeWithText("Refresh status").performClick()
        rule.onNodeWithText("Results").performClick()
        rule.onNodeWithText("Load results").performClick()
        rule.runOnIdle {
            assertEquals(listOf("simulator-status", "simulator-results"), reads)
            assertTrue(commands.isEmpty())
        }
    }
}
