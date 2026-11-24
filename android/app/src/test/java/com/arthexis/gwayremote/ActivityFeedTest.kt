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
        assertEquals(merged, FeedState.fromJson(JSONObject(merged.json().toString())))
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

    @Test fun malformedPageIsRejected() {
        assertTrue(runCatching { parseFeedPage(JSONObject("""{"items":[],"next_cursor":null,"has_more":true}""")) }.isFailure)
    }
}
