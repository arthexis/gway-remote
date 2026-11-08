package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class CompanionSettingsStateTest {
    @Test fun defaultsAndMissingCredentials() {
        assertFalse(CompanionSettingsState.initial("https://remote.arthexis.com", "secret").open)
        assertTrue(CompanionSettingsState.initial("", "secret").open)
        assertTrue(CompanionSettingsState.initial("https://remote.arthexis.com", "").open)
        assertTrue(CompanionSettingsState.initial("", "").open)
    }

    @Test fun togglingDoesNotAlterCredentials() {
        val before = CompanionSettingsState.initial("https://example.test", "token")
        val after = before.toggle()
        assertTrue(after.open)
        assertEquals(before.endpoint, after.endpoint)
        assertEquals(before.token, after.token)
        assertEquals(before, after.toggle())
    }

    @Test fun savingClosesWithoutChangingCredentials() {
        val before = CompanionSettingsState.initial("https://example.test", "token").toggle()
        assertEquals(before.copy(open = false), before.saved())
    }

    @Test fun inputChangesRemainIndependentAndUntrimmedUntilValidation() {
        val before = CompanionSettingsState.initial("https://example.test", "token")
        val after = before.copy(endpoint = " https://new.example ", token = " new-token ")
        assertEquals(" https://new.example ", after.endpoint)
        assertEquals(" new-token ", after.token)
        assertEquals("https://example.test", before.endpoint)
        assertEquals("token", before.token)
    }
}
