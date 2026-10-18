package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class LcdInputTest {
    @Test fun acceptsPrintableAsciiUpToSixteenCharacters() {
        assertTrue(LcdInput.validLine(""))
        assertTrue(LcdInput.validLine("1234567890123456"))
        assertTrue(LcdInput.validLine(" ~"))
        assertFalse(LcdInput.validLine("12345678901234567"))
        assertFalse(LcdInput.validLine("line\nnext"))
        assertFalse(LcdInput.validLine("é"))
        assertFalse(LcdInput.validLine("\u007f"))
    }

    @Test fun durationHasInclusiveBoundsAndRejectsNonNumbers() {
        assertTrue(LcdInput.validDuration("30"))
        assertTrue(LcdInput.validDuration("300"))
        listOf("29", "301", "", "invalid", "30.5").forEach {
            assertFalse(LcdInput.validDuration(it))
        }
    }

    @Test fun executionRequiresTextValidDurationAndIdlePanel() {
        val valid = mapOf("line1" to "Hello", "line2" to "")
        assertTrue(LcdInput.canExecute(valid, false))
        assertFalse(LcdInput.canExecute(valid, true))
        assertFalse(LcdInput.canExecute(emptyMap(), false))
        assertFalse(LcdInput.canExecute(mapOf("line2" to "Hello", "duration" to "29"), false))
        assertFalse(LcdInput.canExecute(mapOf("line1" to "é"), false))
        assertTrue(LcdInput.canExecute(mapOf("line2" to "World", "duration" to "300"), false))
    }

    @Test fun payloadDefaultsDurationAndPreservesOtherParameters() {
        assertEquals(mapOf("line1" to "Hello", "duration" to "30"),
            LcdInput.payload(mapOf("line1" to "Hello")))
        assertEquals(mapOf("line2" to "World", "duration" to "60"),
            LcdInput.payload(mapOf("line2" to "World", "duration" to "60")))
    }
}
