package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.odoo.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class OdooOpportunityTest {
    private fun row(id: Int = 1, state: String? = null, disposition: String = "pending") =
        JSONObject().put("id", id).put("customer", "Cliente de prueba")
            .put("phone", "5550100000").put("complete_address", "Calle de prueba 10, Ciudad")
            .put("priority", "Urgente").put("request_type", "new")
            .put("vehicle_model", "Modelo de prueba").put("vin", "TESTVIN0000000001")
            .put("consent_url", "https://drive.google.com/file/d/test_document_123/view")
            .put("quotation_state", state ?: JSONObject.NULL).put("disposition", disposition)

    private fun response(vararg rows: JSONObject, next: Boolean = false) =
        JSONObject().put("result", JSONObject().put("opportunities", JSONArray(rows.toList()))
            .put("has_next", next))

    @Test fun exactFiveCopyValues() {
        val r = parseOpportunityPage(response(row())).rows.single()
        assertEquals(listOf("Cliente de prueba", "5550100000", "Calle de prueba 10, Ciudad",
            "Urgente - Nueva - Modelo de prueba", "TESTVIN0000000001"), r.copyValues)
        assertEquals("Por cotizar", r.status)
    }

    @Test fun stageNameIsDynamicAndBackwardCompatible() {
        val r = parseOpportunityPage(response(row().put("stage_id", 987).put("stage_name", "Pre-Check"))).rows.single()
        assertEquals(987, r.stageId)
        assertEquals("Pre-Check", r.status)
        assertEquals("Por cotizar", parseOpportunityPage(response(row())).rows.single().status)
    }

    @Test fun onlyAssociatedSentOrLaterAndExplicitlyClosedAreExcluded() {
        val p = parseOpportunityPage(response(row(1), row(2, "draft"), row(3, "sent"),
            row(4, "sale"), row(5, "done"), row(6, null, "lost"), row(7, "cancel"),
            row(8, null, "cancelled"), next = true))
        assertEquals(listOf(1, 2, 7), p.rows.map { it.id })
        assertEquals("Cotización por enviar", p.rows[1].status)
        assertTrue(p.hasNext)
    }

    @Test fun requestTypeIsNormalizedAndIncompleteValuesAreNotInvented() {
        val r = parseOpportunityPage(response(row().put("request_type", "remove_and_install")
            .put("phone", JSONObject.NULL))).rows.single()
        assertEquals("", r.copyValues[1])
        assertEquals("Urgente - Desmontado y Montado - Modelo de prueba", r.copyValues[3])
        assertEquals("", parseOpportunityPage(response(row().put("request_type", "unknown")))
            .rows.single().copyValues[3])
    }

    @Test fun onlyDirectDriveDocumentLinksAreAllowed() {
        val good = "https://drive.google.com/file/d/test_document_123/view"
        assertEquals(good, consentDocumentUrl(good))
        listOf("http://drive.google.com/file/d/test_document_123/view",
            "https://drive.google.com.evil.test/file/d/test_document_123/view",
            "https://user@drive.google.com/file/d/test_document_123/view",
            "https://drive.google.com/file/d/test_document_123/view?token=secret",
            "https://drive.google.com/drive/folders/test_document_123",
            "javascript:alert(1)").forEach { assertNull(consentDocumentUrl(it)) }
    }

    @Test fun duplicateIdsAndUnknownStatesFailClosed() {
        assertTrue(runCatching { parseOpportunityPage(response(row(1), row(1))) }.isFailure)
        assertTrue(runCatching { parseOpportunityPage(response(row(state = "unknown"))) }.isFailure)
        assertTrue(runCatching { parseOpportunityPage(response(row(disposition = "unknown"))) }.isFailure)
    }

    @Test fun nativeNavigationEntryDoesNotGrantCommandAuthority() {
        val feature = FeatureRegistry.get("odoo-opportunities")!!
        assertEquals(FeatureKind.LOCAL_PANEL, feature.kind)
        assertNull(feature.operation)
        assertEquals(ModuleDestination.Screen("odoo-opportunities"),
            ModuleRegistry.get("odoo-opportunities")!!.destination)
    }
}
