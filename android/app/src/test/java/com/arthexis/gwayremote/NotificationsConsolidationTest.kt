package com.arthexis.gwayremote

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class NotificationsConsolidationTest {
    private class FakeRunner : OperationRunner {
        data class Pending(val request: OperationRequest, val result: CompletableDeferred<JSONObject>)
        val pending = mutableListOf<Pending>()
        override suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject {
            val item = Pending(request, CompletableDeferred())
            pending.add(item)
            return item.result.await()
        }
    }

    @Test fun separateCommandsRequireExplicitExecutionAndPreserveParameters() {
        val scope = TestScope(StandardTestDispatcher())
        val fake = FakeRunner()
        val model = OperationViewModel(fake, scope)
        model.open("notifications")
        scope.advanceUntilIdle()
        assertTrue(fake.pending.isEmpty())
        model.notificationInput("sound", "motif", "github")
        model.notificationInput("sound", "sound", "notice")
        model.executeNotification("sound", model.soundNotification.inputs)
        scope.advanceUntilIdle()
        assertEquals("sound-play", fake.pending.single().request.command)
        assertEquals("github", fake.pending.single().request.parameters["motif"])
        assertEquals("notice", fake.pending.single().request.parameters["sound"])
        model.notificationInput("lcd", "line1", "Hello")
        model.executeNotification("lcd", model.lcdNotification.inputs)
        scope.advanceUntilIdle()
        assertEquals("lcd-message", fake.pending[1].request.command)
        assertEquals("Hello", fake.pending[1].request.parameters["line1"])
        assertEquals(30, fake.pending[1].request.parameters["duration_seconds"])
    }

    @Test fun closeReopenDiscardsPriorResultsAndInputs() {
        val scope = TestScope(StandardTestDispatcher())
        val fake = FakeRunner()
        val model = OperationViewModel(fake, scope)
        model.open("notifications")
        model.executeNotification("sound", mapOf("sound" to "notice"))
        scope.advanceUntilIdle()
        model.close("notifications")
        model.open("notifications")
        fake.pending.single().result.complete(JSONObject().put("result", "stale"))
        scope.advanceUntilIdle()
        assertNull(model.soundNotification.output)
        assertTrue(model.soundNotification.inputs.isEmpty())
        model.executeNotification("sound", mapOf("sound" to "notice"))
        scope.advanceUntilIdle()
        fake.pending[1].result.complete(JSONObject().put("result", "fresh"))
        scope.advanceUntilIdle()
        assertTrue(model.soundNotification.output!!.contains("fresh"))
    }

    @Test fun hiddenOperationsRetainBackendContracts() {
        assertEquals(OperationVisibility.PALETTE, OperationRegistry.get("notifications")?.visibility)
        for (kind in listOf("lcd", "sound")) {
            assertEquals(OperationVisibility.INTERNAL, OperationRegistry.get(kind)?.visibility)
            assertNull(FeatureRegistry.get(kind))
            assertNotNull(OperationRequests.explicit(kind, emptyMap()))
        }
    }
}
