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
class SystemConsolidationTest {
    private class FakeRunner : OperationRunner {
        data class Pending(val request: OperationRequest, val value: CompletableDeferred<JSONObject>)
        val pending = mutableListOf<Pending>()
        override suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject {
            val item = Pending(request, CompletableDeferred())
            pending.add(item)
            return item.value.await()
        }
    }
    private fun setup(): Triple<OperationViewModel, FakeRunner, TestScope> {
        val scope = TestScope(StandardTestDispatcher())
        val runner = FakeRunner()
        return Triple(OperationViewModel(runner, scope), runner, scope)
    }

    @Test fun bothChecksAreIndependentAndRetainBackendContracts() {
        val (model, runner, scope) = setup()
        model.open("system")
        scope.advanceUntilIdle()
        assertEquals(listOf("/api/v1/health", "/api/v1/execute"), runner.pending.map { it.request.path })
        assertEquals("status-quick", runner.pending[1].request.command)
        runner.pending[0].value.complete(JSONObject().put("result", "connected"))
        runner.pending[1].value.completeExceptionally(IllegalStateException("status unavailable"))
        scope.advanceUntilIdle()
        assertTrue(model.apiHealth.output!!.contains("connected"))
        assertNull(model.apiHealth.error)
        assertEquals("status unavailable", model.systemStatus.error)
        assertNull(model.systemStatus.output)
    }

    @Test fun refreshAndCloseRejectOldResponses() {
        val (model, runner, scope) = setup()
        model.open("system")
        scope.advanceUntilIdle()
        model.refreshSystem("api-health")
        scope.advanceUntilIdle()
        runner.pending[2].value.complete(JSONObject().put("result", "new"))
        scope.advanceUntilIdle()
        runner.pending[0].value.complete(JSONObject().put("result", "old"))
        scope.advanceUntilIdle()
        assertTrue(model.apiHealth.output!!.contains("new"))
        model.close("system")
        model.open("system")
        scope.advanceUntilIdle()
        runner.pending[1].value.complete(JSONObject().put("result", "stale status"))
        scope.advanceUntilIdle()
        assertNull(model.systemStatus.output)
        runner.pending[4].value.complete(JSONObject().put("result", "fresh status"))
        scope.advanceUntilIdle()
        assertTrue(model.systemStatus.output!!.contains("fresh status"))
    }
}
