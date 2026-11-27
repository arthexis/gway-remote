package com.arthexis.gwayremote

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import com.arthexis.gwayremote.features.odoo.OdooOpportunitiesPanel
import com.arthexis.gwayremote.features.odoo.consentDocumentUrl
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList

/** Synthetic response fixtures only. Never calls Odoo or opens a real document. */
class AndroidRcOpportunityContractTest {
    @get:Rule val rule = createComposeRule()

    private fun result(customer: String, url: String, next: Boolean = false): JSONObject {
        val row = JSONObject().put("id", 42).put("customer", customer)
            .put("phone", "5550100000").put("complete_address", "Fixture address")
            .put("priority", "Alta").put("request_type", "new").put("vehicle_model", "Fixture model")
            .put("vin", "TESTVIN0000000001").put("disposition", "pending")
            .put("consent_url", url).put("quotation_state", JSONObject.NULL)
        return JSONObject().put("result", JSONObject().put("opportunities", JSONArray().put(row))
            .put("has_next", next))
    }

    private fun refresh() {
        rule.onNodeWithTag("odoo-opportunities-refresh").performTouchInput { swipeDown() }
    }

    @Test fun refreshRetainsStaleRecordsAndRecovers() {
        val calls = CopyOnWriteArrayList<Int>()
        rule.setContent {
            MaterialTheme {
                OdooOpportunitiesPanel("https://example.invalid", "fixture") { _, _, page ->
                    calls.add(page)
                    when (calls.size) {
                        1 -> result("Fixture initial", "https://example.invalid/unsafe")
                        2 -> error("fixture offline")
                        else -> result("Fixture recovered", "https://example.invalid/unsafe")
                    }
                }
            }
        }
        rule.onNodeWithText("Fixture initial").assertExists()
        rule.onNodeWithText("Consentimiento").assertIsNotEnabled()
        rule.onNodeWithText("Carta no disponible").assertExists()
        refresh()
        rule.waitUntil(5000) { calls.size == 2 }
        rule.onNodeWithText("Fixture initial").assertExists()
        rule.onNodeWithText("No se pudo actualizar. Se muestran los últimos datos recibidos.").assertExists()
        refresh()
        rule.waitUntil(5000) { calls.size == 3 }
        rule.onNodeWithText("Fixture recovered").assertExists()
        rule.onNodeWithText("Fixture initial").assertDoesNotExist()
        rule.onNodeWithText("No se pudo actualizar. Se muestran los últimos datos recibidos.").assertDoesNotExist()
        assertEquals(listOf(1, 1, 1), calls.toList())
    }

    @Test fun paginationAndConsentValidation() {
        val calls = CopyOnWriteArrayList<Int>()
        val safe = "https://drive.google.com/file/d/fixture_document_123/view"
        rule.setContent {
            MaterialTheme {
                OdooOpportunitiesPanel("https://example.invalid", "fixture") { _, _, page ->
                    calls.add(page)
                    if (page == 1) result("Fixture page one", safe, next = true)
                    else result("Fixture page two", safe + "?token=fixture")
                }
            }
        }
        rule.onNodeWithText("Fixture page one").assertExists()
        rule.onNodeWithText("Consentimiento").assertIsEnabled()
        rule.onNodeWithText("Anterior").assertIsNotEnabled()
        rule.onNodeWithText("Siguiente").performScrollTo().performClick()
        rule.waitUntil(5000) { calls.size == 2 }
        rule.onNodeWithText("Fixture page two").assertExists()
        rule.onNodeWithText("Consentimiento").assertIsNotEnabled()
        rule.onNodeWithText("Página 2").assertExists()
        rule.onNodeWithText("Siguiente").assertIsNotEnabled()
        rule.onNodeWithText("Anterior").performScrollTo().performClick()
        rule.waitUntil(5000) { calls.size == 3 }
        rule.onNodeWithText("Fixture page one").assertExists()
        assertEquals(safe, consentDocumentUrl(safe))
        assertNull(consentDocumentUrl(safe + "?token=fixture"))
        assertEquals(listOf(1, 2, 1), calls.toList())
    }

    @Test fun missingCredentialsNeverCallOpportunityBackend() {
        val calls = CopyOnWriteArrayList<Int>()
        rule.setContent {
            MaterialTheme {
                OdooOpportunitiesPanel("https://example.invalid", "") { _, _, page ->
                    calls.add(page)
                    error("must not call")
                }
            }
        }
        rule.onNodeWithText("Configura el acceso de GWay Remote.").assertExists()
        rule.runOnIdle { assertTrue(calls.isEmpty()) }
    }
}
