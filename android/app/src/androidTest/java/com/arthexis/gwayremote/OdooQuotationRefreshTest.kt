package com.arthexis.gwayremote

import android.app.Activity
import android.content.Intent
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.core.app.ActivityOptionsCompat
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.arthexis.gwayremote.features.odoo.OdooQuotationsPanel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.CompletableDeferred

/** Physical-device-safe UI scenarios: fake read API, no real Odoo or file writes. */
class OdooQuotationRefreshTest {
    @get:Rule val rule = createComposeRule()

    private fun row(folio: String, suggested: String? = null): JSONObject =
        JSONObject().put("id", 1).put("name", folio).put("customer", "Cliente prueba")
            .put("state", "draft").put("date", "2026-01-01").put("total", 100)
            .put("currency", "MXN").put("suggested_pdf_filename", suggested ?: JSONObject.NULL)

    private fun result(folio: String? = null, next: Boolean = false, suggested: String? = null): JSONObject =
        JSONObject().put("result", JSONObject().put("has_next", next)
            .put("quotations", if (folio == null) JSONArray() else JSONArray().put(row(folio, suggested))))

    private fun swipeRefresh() {
        rule.onNodeWithTag("odoo-quotations-refresh").performTouchInput { swipeDown() }
    }

    private fun search(query: String) {
        rule.onNodeWithText("Folio o cliente").performTextInput(query)
        rule.onNodeWithText("Buscar").performClick()
    }

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
        search("Porsche")
        rule.onNodeWithText("S200").assertExists()
        swipeRefresh()
        rule.waitUntil(5000) { requests.size == 3 }
        rule.onNodeWithText("Buscando…").assertExists()
        rule.onNodeWithText("S200").assertExists()
        rule.onNodeWithText("Buscando…").assertIsNotEnabled()
        swipeRefresh()
        assertEquals(3, requests.size)
        gate.complete(Unit)
        rule.onNodeWithText("S201").assertExists()
        swipeRefresh()
        rule.waitUntil(5000) { requests.size == 4 }
        rule.onNodeWithText("S201").assertExists()
        rule.onNodeWithText("No se pudieron cargar las cotizaciones: Test connection failure").assertExists()
        assertEquals(listOf("" to 1, "Porsche" to 1, "Porsche" to 1, "Porsche" to 1), requests.toList())
    }

    @Test fun pagingAndRecentResetKeepCorrectQuery() {
        val requests = CopyOnWriteArrayList<Pair<String, Int>>()
        rule.setContent {
            MaterialTheme {
                OdooQuotationsPanel("https://example.invalid", "test") { _, _, query, page ->
                    requests.add(query to page)
                    result(if (query.isEmpty()) "S100" else if (page == 1) "S200" else "S300",
                        next = page == 1)
                }
            }
        }
        rule.onNodeWithText("S100").assertExists()
        search("Audi")
        rule.onNodeWithText("S200").assertExists()
        rule.onNodeWithText("Anterior").assertIsNotEnabled()
        rule.onNodeWithText("Siguiente").performClick()
        rule.onNodeWithText("S300").assertExists()
        rule.onNodeWithText("Página 2").assertExists()
        rule.onNodeWithText("Siguiente").assertIsNotEnabled()
        swipeRefresh()
        rule.waitUntil(5000) { requests.size == 4 }
        rule.onNodeWithText("S300").assertExists()
        rule.onNodeWithText("Anterior").performClick()
        rule.onNodeWithText("S200").assertExists()
        rule.onNodeWithText("Recientes").performClick()
        rule.onNodeWithText("S100").assertExists()
        assertEquals(listOf("" to 1, "Audi" to 1, "Audi" to 2, "Audi" to 2,
            "Audi" to 1, "" to 1), requests.toList())
    }

    @Test fun emptyAndInitialErrorAreRecoverable() {
        val requests = CopyOnWriteArrayList<String>()
        rule.setContent {
            MaterialTheme {
                OdooQuotationsPanel("https://example.invalid", "test") { _, _, query, _ ->
                    requests.add(query)
                    when (requests.size) {
                        1 -> error("Offline")
                        2 -> result()
                        else -> result("S100")
                    }
                }
            }
        }
        rule.onNodeWithText("No se pudieron cargar las cotizaciones: Offline").assertExists()
        swipeRefresh()
        rule.onNodeWithText("No hay cotizaciones para esta búsqueda.").assertExists()
        swipeRefresh()
        rule.onNodeWithText("S100").assertExists()
        assertEquals(listOf("", "", ""), requests.toList())
    }

    @Test fun missingCredentialsNeverCallBackend() {
        val requests = CopyOnWriteArrayList<String>()
        rule.setContent {
            MaterialTheme {
                OdooQuotationsPanel("", "") { _, _, query, _ ->
                    requests.add(query)
                    error("Unexpected network request")
                }
            }
        }
        rule.onNodeWithText("Configura el endpoint HTTPS y el token de GWay Remote.").assertExists()
        assertEquals(emptyList<String>(), requests.toList())
    }

    @Test fun actualSaveContractUsesSuggestedNameAndLegacyFallback() {
        val titles = CopyOnWriteArrayList<String>()
        val registry = object : ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>,
                                         input: I, options: ActivityOptionsCompat?) {
                val intent = contract.createIntent(
                    InstrumentationRegistry.getInstrumentation().targetContext, input)
                assertEquals(Intent.ACTION_CREATE_DOCUMENT, intent.action)
                assertEquals("application/pdf", intent.type)
                titles.add(requireNotNull(intent.getStringExtra(Intent.EXTRA_TITLE)))
                dispatchResult(requestCode, Activity.RESULT_CANCELED, null)
            }
        }
        val owner = object : ActivityResultRegistryOwner {
            override val activityResultRegistry = registry
        }
        rule.setContent {
            MaterialTheme {
                CompositionLocalProvider(LocalActivityResultRegistryOwner provides owner) {
                    OdooQuotationsPanel("https://example.invalid", "test") { _, _, query, _ ->
                        if (query.isEmpty()) result("S100", suggested = "Cotización S100 CP - Porsche.pdf")
                        else result("S200")
                    }
                }
            }
        }
        rule.onNodeWithContentDescription("Descargar PDF de S100").performClick()
        rule.waitUntil(5000) { titles.size == 1 }
        search("legacy")
        rule.onNodeWithContentDescription("Descargar PDF de S200").performClick()
        rule.waitUntil(5000) { titles.size == 2 }
        assertEquals(listOf("Cotización S100 CP - Porsche.pdf", "S200.pdf"), titles.toList())
    }
}
