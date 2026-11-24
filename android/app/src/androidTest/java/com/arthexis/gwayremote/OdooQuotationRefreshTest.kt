package com.arthexis.gwayremote

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.arthexis.gwayremote.features.odoo.OdooQuotationsPanel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.CompletableDeferred

class OdooQuotationRefreshTest {
    @get:Rule val rule = createComposeRule()

    private fun result(folio: String): JSONObject = JSONObject().put("result",
        JSONObject().put("has_next", false).put("quotations", JSONArray().put(
            JSONObject().put("id", 1).put("name", folio).put("customer", "Cliente prueba")
                .put("state", "draft").put("date", "2026-11-24").put("total", 100))))

    @Test fun refreshKeepsFilterAndLastGoodResults() {
        val requests = CopyOnWriteArrayList<Pair<String, Int>>()
        val gate = CompletableDeferred<Unit>()
        rule.setContent {
            MaterialTheme {
                OdooQuotationsPanel("https://example.invalid", "test") { _, _, query, page ->
                    requests.add(query to page)
                    when (requests.size) {
                        1 -> result("S100")
                        2 -> result("S200")
                        3 -> { gate.await(); result("S201") }
                        else -> error("Test connection failure")
                    }
                }
            }
        }
        rule.onNodeWithText("S100").assertExists()
        rule.onNodeWithText("Folio o cliente").performTextInput("Porsche")
        rule.onNodeWithText("Buscar").performClick()
        rule.onNodeWithText("S200").assertExists()
        rule.onNodeWithTag("odoo-quotations-refresh").performTouchInput { swipeDown() }
        rule.waitUntil(5000) { requests.size == 3 }
        rule.onNodeWithText("Buscando…").assertExists()
        rule.onNodeWithText("S200").assertExists()
        gate.complete(Unit)
        rule.waitUntil(5000) { rule.onAllNodesWithText("S201").fetchSemanticsNodes().isNotEmpty() }
        rule.onNodeWithTag("odoo-quotations-refresh").performTouchInput { swipeDown() }
        rule.waitUntil(5000) { requests.size == 4 }
        rule.onNodeWithText("S201").assertExists()
        rule.onNodeWithText("No se pudieron cargar las cotizaciones: Test connection failure").assertExists()
        assertEquals(listOf("" to 1, "Porsche" to 1, "Porsche" to 1, "Porsche" to 1), requests.toList())
    }
}
