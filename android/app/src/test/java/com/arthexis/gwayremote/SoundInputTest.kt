package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class SoundInputTest {
    @Test fun defaultsToNoticeAndNoMotif() {
        assertEquals("notice", SoundInput.sound(emptyMap()))
        assertEquals("", SoundInput.motif(emptyMap()))
        assertEquals(mapOf("sound" to "notice", "motif" to ""), SoundInput.payload(emptyMap()))
        assertTrue(SoundInput.valid(emptyMap(), emptyList()))
    }

    @Test fun acceptsOnlyKnownSounds() {
        SoundInput.choices.forEach { sound ->
            assertTrue(SoundInput.valid(mapOf("sound" to sound), emptyList()))
        }
        assertFalse(SoundInput.valid(mapOf("sound" to "unknown"), emptyList()))
    }

    @Test fun motifMustExistUnlessOmitted() {
        val available = listOf("arrival", "success")
        assertTrue(SoundInput.valid(mapOf("motif" to "arrival"), available))
        assertTrue(SoundInput.valid(mapOf("motif" to ""), available))
        assertFalse(SoundInput.valid(mapOf("motif" to "missing"), available))
        assertFalse(SoundInput.valid(mapOf("motif" to "arrival"), emptyList()))
    }

    @Test fun executionIsBlockedWhileLoading() {
        val input = mapOf("sound" to "warning", "motif" to "arrival")
        assertTrue(SoundInput.canExecute(input, listOf("arrival"), false))
        assertFalse(SoundInput.canExecute(input, listOf("arrival"), true))
        assertFalse(SoundInput.canExecute(input, emptyList(), false))
    }

    @Test fun payloadUsesOnlyTheTwoCommandArguments() {
        val inputs = mapOf("sound" to "critical", "motif" to "arrival", "unrelated" to "ignored")
        assertEquals(mapOf("sound" to "critical", "motif" to "arrival"), SoundInput.payload(inputs))
    }
}
