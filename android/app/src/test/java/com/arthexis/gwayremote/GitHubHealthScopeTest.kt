package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.githubhealth.isSupportedHealthScope
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The cached watch can report fewer repositories than the app's supported catalog. */
class GitHubHealthScopeTest {
    @Test fun configuredTwoRepositoryWatchIsAccepted() {
        assertTrue(isSupportedHealthScope(setOf("arthexis/ocpp-csms", "arthexis/ocpp-simulator")))
    }

    @Test fun singleSupportedRepositoryIsAccepted() {
        assertTrue(isSupportedHealthScope(setOf("arthexis/gway-remote")))
    }

    @Test fun emptyAndUnexpectedScopesAreRejected() {
        assertFalse(isSupportedHealthScope(emptySet()))
        assertFalse(isSupportedHealthScope(setOf("other/private-repository")))
        assertFalse(isSupportedHealthScope(setOf("arthexis/ocpp-csms", "other/unexpected")))
    }
}
