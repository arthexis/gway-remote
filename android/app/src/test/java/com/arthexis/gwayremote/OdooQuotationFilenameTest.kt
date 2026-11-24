package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.odoo.localQuotationFilename
import org.junit.Assert.assertEquals
import org.junit.Test

class OdooQuotationFilenameTest {
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
