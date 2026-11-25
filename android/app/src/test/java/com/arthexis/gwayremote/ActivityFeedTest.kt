package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.feed.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ActivityFeedTest {
    private fun item(seq: Long, category: String = "deployment") =
        FeedItem(seq, "Deploy $seq", "Complete", category, "success", "2026-11-24T10:00:00Z", "2026-11-24T10:00:00Z")

    @Test fun paginationDedupReadAndCacheRoundTrip() {
        val initial = FeedState().merge(FeedPage(listOf(item(3), item(2)), 2, true), true, 100).mark(3)
        val merged = initial.merge(FeedPage(listOf(item(2), item(1, "fleet")), 1, false), false, 200)
        assertEquals(listOf(3L, 2L, 1L), merged.items.map { it.seq })
        assertEquals(setOf(3L), merged.read)
        assertEquals(listOf(1L), merged.visible("fleet").map { it.seq })
        val restored = FeedState.fromJson(JSONObject(merged.json().toString()))
        assertEquals(merged, restored)
        assertEquals(listOf(2L, 1L), restored.visible(null).map { it.seq })
        assertEquals(listOf(2L), restored.visible("deployment").map { it.seq })
        val refreshed = restored.merge(FeedPage(listOf(item(4), item(3), item(2)), 2, true), true, 300)
        assertEquals(listOf(4L, 2L), refreshed.visible(null).map { it.seq })
        assertEquals(setOf(3L), merged.merge(FeedPage(listOf(item(4)), 4, true), true, 300).read)
    }

    @Test fun linksAndModuleNavigationAreRestricted() {
        assertEquals("deployments", item(1).moduleId)
        assertNull(item(1, "unknown").moduleId)
        assertNotNull(safeFeedLink("https://github.com/arthexis/gway-remote/issues/705"))
        for (url in listOf("http://github.com/arthexis/a", "https://evil.test/x",
            "https://github.com/other/a", "https://github.com/arthexis/a?token=x",
            "https://user@github.com/arthexis/a")) assertNull(safeFeedLink(url))
    }

    @Test fun isolatedCanaryOriginNeverFallsBack() {
        assertEquals("https://remote.arthexis.com/api/v1/feed/events?limit=20", feedTarget(PRODUCTION_PACKAGE, null).toString())
        assertEquals("https://127.0.0.1:18443/api/feed/events?limit=20&before=7", feedTarget(CANARY_PACKAGE, 7).toString())
        assertTrue(runCatching { feedOrigin("com.other.app") }.isFailure)
        assertTrue(runCatching { feedTarget(CANARY_PACKAGE, 0) }.isFailure)
        assertTrue(runCatching { loadCanaryCertificate(java.io.File("/nonexistent/canary-cert.der")) }.isFailure)
    }

    @Test fun mobileKeyUsesConfiguredHttpsOriginWithoutCanaryFallback() {
        assertEquals("https://example.test:8443/api/v1/feed/events?limit=20&before=9",
            feedTarget(PRODUCTION_PACKAGE, 9, "https://example.test:8443/").toString())
        assertEquals("https://127.0.0.1:18443/api/feed/events?limit=20",
            feedTarget(CANARY_PACKAGE, null, "https://example.test").toString())
        for (bad in listOf("http://example.test", "https://user@example.test", "https://example.test/x",
            "https://example.test?q=1", "https://example.test/#fragment")) {
            assertTrue(runCatching { feedTarget(PRODUCTION_PACKAGE, null, bad) }.isFailure)
        }
        assertTrue(validMobileFeedKey("legacy-mobile-key"))
        assertTrue(validMobileFeedKey("gwymob1_" + "a".repeat(24) + "_" + "b".repeat(43)))
        assertFalse(validMobileFeedKey("bad\nheader"))
        assertFalse(validMobileFeedKey(" "))
        assertFalse(validMobileFeedKey("x".repeat(154)))
    }

    @Test fun malformedPageIsRejected() {
        assertTrue(runCatching { parseFeedPage(JSONObject("""{"items":[],"next_cursor":null,"has_more":true}""")) }.isFailure)
    }
}
