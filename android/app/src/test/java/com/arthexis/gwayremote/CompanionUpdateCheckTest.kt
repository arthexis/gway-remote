package com.arthexis.gwayremote

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class CompanionUpdateCheckTest {
    private val candidate = AvailableUpdate("2.1", 21L, "https://example.test/app.apk", "abc", 100L)

    @Test fun availableUpdateEmitsCandidateThenStatusThenFinished() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateCheck.run(
            { events.add("check"); candidate },
            { events.add("update:${it?.version}") },
            { events.add("status:$it") },
            { events.add("finished") }
        )
        assertEquals(listOf("check", "update:2.1", "status:Update available: 2.1", "finished"), events)
    }

    @Test fun upToDateClearsCandidateAndFinishes() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateCheck.run(
            { null }, { events.add("update:${it?.version}") },
            { events.add(it) }, { events.add("finished") }
        )
        assertEquals(listOf("update:null", "App is up to date", "finished"), events)
    }

    @Test fun requestErrorKeepsExistingCandidateAndFinishes() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateCheck.run(
            { throw IllegalStateException("offline") },
            { events.add("update") }, { events.add(it) }, { events.add("finished") }
        )
        assertEquals(listOf("offline", "finished"), events)
    }

    @Test fun nullErrorMessageUsesOriginalFallback() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateCheck.run(
            { throw IllegalStateException() },
            {}, { events.add(it) }, { events.add("finished") }
        )
        assertEquals(listOf("Update check failed", "finished"), events)
    }

    @Test fun callbackErrorAlsoResetsRunning() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateCheck.run(
            { candidate }, { throw IllegalArgumentException("state") },
            { events.add(it) }, { events.add("finished") }
        )
        assertEquals(listOf("state", "finished"), events)
    }
}
