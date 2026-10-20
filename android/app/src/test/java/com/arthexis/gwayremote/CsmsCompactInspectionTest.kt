package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CsmsCompactInspectionTest {
    @Test fun recognizesSemanticStatesWithoutAssumingFixedColumnWidths() {
        val charging = CsmsLine.parse("CP-001     Charging     1h 24m")
        assertEquals("CP-001", charging.label)
        assertEquals("Charging", charging.state)
        assertTrue(charging.detail.contains("1h 24m"))
        assertEquals("Faulted", CsmsLine.parse("CP-002 | Faulted").state)
    }

    @Test fun durationCompactFormattingPreservesUnrecognizedText() {
        assertEquals("1h 2m", compactDuration("1 hour 2 minutes"))
        assertEquals("2d 3h", compactDuration("2 days 3 hours"))
        assertEquals("not recorded", compactDuration("not recorded"))
    }

    @Test fun malformedOrSingleColumnRowsRemainVisible() {
        val line = CsmsLine.parse("opaque charger identifier")
        assertEquals("opaque charger identifier", line.label)
        assertNull(line.state)
    }
}
