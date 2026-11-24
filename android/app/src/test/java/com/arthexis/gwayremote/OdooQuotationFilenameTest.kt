package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.odoo.localQuotationFilename
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Test

class OdooQuotationFilenameTest {
    @Test fun nativeTransferNameRemainsIndependentOfSuggestion() {
        assertTrue(OdooPdfTransfer.matchesOfficialFilename("Cotización S30979.pdf", "S30979"))
        assertTrue(OdooPdfTransfer.matchesOfficialFilename("S30979.pdf", "S30979"))
        assertFalse(OdooPdfTransfer.matchesOfficialFilename("Cotización S30979 ADL - Porsche.pdf", "S30979"))
        assertFalse(OdooPdfTransfer.matchesOfficialFilename("Cotización S30980.pdf", "S30979"))
    }

    @Test fun validSuggestion() {
        assertEquals("Cotización S30979 ADL - Porsche.pdf",
            localQuotationFilename("S30979", "Cotización S30979 ADL - Porsche.pdf"))
    }

    @Test fun fallbackForMissingOrUnsafeSuggestion() {
        for (suggestion in listOf(null, "Cotización S30980 ADL - Porsche.pdf",
            "Cotización S30979 ADL - ../Porsche.pdf", "wrong.pdf")) {
            assertEquals("S30979.pdf", localQuotationFilename("S30979", suggestion))
        }
    }
}
