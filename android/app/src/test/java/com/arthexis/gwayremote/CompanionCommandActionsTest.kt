package com.arthexis.gwayremote

import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CompanionCommandActionsTest {
    @Test fun performCatalogPreservesOrderAndCallbackSequence() = runBlocking {
        val calls = mutableListOf<String>()
        CompanionCommandActions.perform(
            "/api/v1/commands",
            {
                calls.add("request")
                JSONObject("""{"commands":[{"name":"status","read_only":true},{"name":"status","read_only":true}]}""")
            },
            { calls.add("catalog:${it.joinToString(",")}") },
            { calls.add("result:${JSONObject(it).getJSONArray("commands").length()}") },
            { _, _ -> fail("Unexpected error") }
        )
        assertEquals(listOf("request", "catalog:status,status", "result:2"), calls)
    }

    @Test fun performNonCatalogOnlyUpdatesResult() = runBlocking {
        var catalogCalled = false
        var value = ""
        CompanionCommandActions.perform(
            "/api/v1/execute", { JSONObject("""{"ok":true}""") },
            { catalogCalled = true }, { value = it }, { _, _ -> fail("Unexpected error") }
        )
        assertFalse(catalogCalled)
        assertTrue(JSONObject(value).getBoolean("ok"))
    }

    @Test fun performFailureClearsCatalogOnlyForCommands() = runBlocking {
        val failures = mutableListOf<Pair<String, Boolean>>()
        for (path in listOf("/api/v1/commands", "/api/v1/execute")) {
            CompanionCommandActions.perform(
                path, { throw IllegalStateException("offline") }, {}, {},
                { message, clear -> failures.add(message to clear) }
            )
        }
        assertEquals(listOf("offline" to true, "offline" to false), failures)
    }

    @Test fun performMalformedCatalogReportsErrorWithoutResult() = runBlocking {
        var called = false
        var failed = false
        CompanionCommandActions.perform(
            "/api/v1/commands", { JSONObject("""{"commands":[42]}""") },
            {}, { called = true }, { _, clear -> failed = clear }
        )
        assertFalse(called)
        assertTrue(failed)
    }

    @Test fun refreshFetchAggregatesFailuresInOriginalOrder() = runBlocking {
        val failures = mutableListOf<String>()
        val first = CompanionCommandActions.fetch("Health", failures) {
            throw IllegalStateException("offline")
        }
        val second = CompanionCommandActions.fetch("Commands", failures) {
            JSONObject("""{"commands":[]}""")
        }
        val third = CompanionCommandActions.fetch("Quick status", failures) {
            throw IllegalArgumentException("denied")
        }
        assertNull(first)
        assertNotNull(second)
        assertNull(third)
        assertEquals(listOf("Health: offline", "Quick status: denied"), failures)
    }
}
