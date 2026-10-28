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
class RefreshRegistryTest {
    private class Runner : OperationRunner {
        data class Pending(val request: OperationRequest, val done: CompletableDeferred<JSONObject>)
        val pending = mutableListOf<Pending>()
        override suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject {
            val p = Pending(request, CompletableDeferred())
            pending.add(p)
            return p.done.await()
        }
    }

    @Test fun refreshRegistryOnlyIncludesOpenSafePanels() {
        var state = OperationPanelState()
        for (id in listOf("system", "csms", "notifications", "simulator", "benchmark")) {
            state = state.open(id).state
        }
        assertEquals(setOf("system", "csms", "simulator"),
            RefreshRegistry.targets(state).map { it.panelId }.toSet())
        assertFalse(RefreshRegistry.targets(state).any { it.panelId in setOf("notifications", "benchmark") })
    }

    @Test fun pullRefreshDoesNotExecuteMutatingCommandsAndRejectsOldCsmsResults() {
        val scope = TestScope(StandardTestDispatcher())
        val runner = Runner()
        val model = OperationViewModel(runner, scope)
        model.open("csms")
        model.open("notifications")
        scope.advanceUntilIdle()
        model.selectCsmsView("events")
        model.refreshOpenPanels()
        scope.advanceUntilIdle()
        assertTrue(runner.pending.any { it.request.command == "csms-view" })
        assertTrue(runner.pending.none { it.request.command in setOf("lcd-message", "sound-play", "simulator-start", "simulator-stop") })
        model.close("csms")
        model.open("csms")
        scope.advanceUntilIdle()
        runner.pending.filter { it.request.command == "csms-view" }.forEach {
            it.done.complete(JSONObject().put("result", "old events"))
        }
        scope.advanceUntilIdle()
        assertFalse(model.panels.panels.first { it.id == "csms" }.output.orEmpty().contains("old events"))
    }

    @Test fun removedTasksCannotBeRefreshed() {
        val state = OperationPanelState().restore(listOf("tasks", "agent-ops"))
        assertEquals(listOf("agent-ops"), state.panels.map { it.id })
        assertTrue(RefreshRegistry.targets(state).none { it.panelId == "tasks" })
    }
}
