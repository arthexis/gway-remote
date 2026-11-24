package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.odoo.localQuotationFilename
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test

class OdooQuotationFilenameTest {
    @Test fun nativeTransferNameRemainsIndependentOfSuggestion() {
        assertTrue(OdooPdfTransfer.matchesOfficialFilename("Cotización S100.pdf", "S100"))
        assertTrue(OdooPdfTransfer.matchesOfficialFilename("S100.pdf", "S100"))
        assertFalse(OdooPdfTransfer.matchesOfficialFilename("Cotización S100 ADL - Porsche.pdf", "S100"))
        assertFalse(OdooPdfTransfer.matchesOfficialFilename("Cotización S101.pdf", "S100"))
    }

    @Test fun validSuggestion() {
        assertEquals("Cotización S100 ADL - Porsche.pdf",
            localQuotationFilename("S100", "Cotización S100 ADL - Porsche.pdf"))
    }

    @Test fun fallbackForMissingOrUnsafeSuggestion() {
        for (suggestion in listOf(null, "Cotización S101 ADL - Porsche.pdf",
            "Cotización S100 ADL - ../Porsche.pdf", "wrong.pdf")) {
            assertEquals("S100.pdf", localQuotationFilename("S100", suggestion))
        }
    }
}
