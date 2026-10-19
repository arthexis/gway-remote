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
class AsyncOperationViewModelTest {
    private val taskA = "8fc71471-92b8-4202-bda1-3dc4fe348402"
    private val taskB = "11111111-2222-3333-4444-555555555555"

    private class FakeRunner : OperationRunner {
        data class Pending(val request: OperationRequest, val response: CompletableDeferred<JSONObject>)
        val pending = mutableListOf<Pending>()
        override suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject {
            val item = Pending(request, CompletableDeferred())
            pending.add(item)
            return item.response.await()
        }
    }

    private fun fixture(): Triple<OperationViewModel, FakeRunner, TestScope> {
        val scope = TestScope(StandardTestDispatcher())
        val runner = FakeRunner()
        val model = OperationViewModel(runner, scope)
        model.bindCredentials { "https://example.invalid" to "token" }
        return Triple(model, runner, scope)
    }

    @Test fun laterTaskSelectionWinsEvenIfEarlierResponseArrivesLast() {
        val (model, runner, scope) = fixture()
        model.open("tasks")
        scope.advanceUntilIdle()
        assertEquals("codex-tasks", runner.pending.single().request.command)
        model.inspectTask(taskA)
        model.inspectTask(taskB)
        scope.advanceUntilIdle()
        assertEquals(3, runner.pending.size)
        runner.pending[2].response.complete(JSONObject().put("result", "B"))
        scope.advanceUntilIdle()
        assertTrue(model.taskDetail!!.contains("B"))
        runner.pending[1].response.complete(JSONObject().put("result", "A"))
        scope.advanceUntilIdle()
        assertEquals(taskB, model.taskDetailSelection)
        assertTrue(model.taskDetail!!.contains("B"))
        assertFalse(model.taskDetailLoading)
    }

    @Test fun closingAndReopeningTasksRejectsPriorDetailAndHistory() {
        val (model, runner, scope) = fixture()
        model.open("tasks")
        model.inspectTask(taskA)
        scope.advanceUntilIdle()
        model.close("tasks")
        model.open("tasks")
        scope.advanceUntilIdle()
        runner.pending[1].response.complete(JSONObject().put("result", "stale detail"))
        runner.pending[0].response.complete(JSONObject().put("result", "stale history"))
        scope.advanceUntilIdle()
        assertNull(model.taskDetailSelection)
        assertNull(model.taskDetail)
        assertNull(model.panels.panels.single().output)
        runner.pending[2].response.complete(JSONObject().put("result", "fresh history"))
        scope.advanceUntilIdle()
        assertTrue(model.panels.panels.single().output!!.contains("fresh history"))
    }

    @Test fun staleErrorIsIgnoredAndCurrentErrorIsDisplayed() {
        val (model, runner, scope) = fixture()
        model.open("tasks")
        model.inspectTask(taskA)
        model.inspectTask(taskB)
        scope.advanceUntilIdle()
        runner.pending[1].response.completeExceptionally(IllegalStateException("old failure"))
        scope.advanceUntilIdle()
        assertNull(model.taskDetailError)
        runner.pending[2].response.completeExceptionally(IllegalStateException("current failure"))
        scope.advanceUntilIdle()
        assertEquals("current failure", model.taskDetailError)
        assertFalse(model.taskDetailLoading)
    }

    @Test fun csmsRefreshRejectsStaleSuccessAndError() {
        val (model, runner, scope) = fixture()
        model.open("csms")
        scope.advanceUntilIdle()
        model.inspectCsms("events")
        scope.advanceUntilIdle()
        assertEquals("csms-view", runner.pending[1].request.command)
        runner.pending[1].response.complete(JSONObject().put("result", "events"))
        scope.advanceUntilIdle()
        runner.pending[0].response.completeExceptionally(IllegalStateException("old failure"))
        scope.advanceUntilIdle()
        assertTrue(model.panels.panels.single().output!!.contains("events"))
        assertNull(model.panels.panels.single().error)
    }

    @Test fun simulatorReadRejectsStaleResultAndMutationsNeedConfirmation() {
        val (model, runner, scope) = fixture()
        model.selectSimulatorPeer("192.0.2.3", "9000")
        model.execute("simulator-start", emptyMap())
        model.runConfirmedSimulator("unapproved", JSONObject())
        scope.advanceUntilIdle()
        assertTrue(runner.pending.isEmpty())
        model.simulatorRead("simulator-results")
        scope.advanceUntilIdle()
        model.close("simulator")
        model.selectSimulatorPeer("192.0.2.4", "9000")
        model.simulatorRead("simulator-status")
        scope.advanceUntilIdle()
        runner.pending[0].response.complete(JSONObject().put("result", "old"))
        scope.advanceUntilIdle()
        assertNull(model.panels.panels.single().output)
        runner.pending[1].response.complete(JSONObject().put("result", JSONObject().put("state", "ready")))
        scope.advanceUntilIdle()
        assertTrue(model.panels.panels.single().output!!.contains("ready"))
    }
}
