package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.operations.ModuleOperationViewModel

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Controller contract: one active module and no stale or implicit write. */
@OptIn(ExperimentalCoroutinesApi::class)
class ModuleOperationViewModelTest {
    @Test fun navigationNeverRunsNotificationsWithoutExplicitAction() = runTest {
        val requests = mutableListOf<String>()
        val model = ModuleOperationViewModel(OperationRunner { _, _, request ->
            requests.add(request.command.orEmpty())
            JSONObject().put("result", "ok")
        }, this)
        model.bindCredentials { "https://remote.arthexis.com" to "test-token" }
        model.open("notifications")
        runCurrent()
        assertTrue(requests.isEmpty())
        model.notificationInput("sound", "sound", "notice")
        assertEquals("notice", model.soundNotification.inputs["sound"])
        model.executeNotification("sound", model.soundNotification.inputs)
        runCurrent()
        assertEquals(listOf("sound-play"), requests)
        assertFalse(model.soundNotification.loading)
        model.close()
        assertNull(model.current)
        assertTrue(model.soundNotification.inputs.isEmpty())
    }

    @Test fun closedCsmsResponseCannotAttachToAnotherModule() = runTest {
        val pending = CompletableDeferred<JSONObject>()
        val model = ModuleOperationViewModel(OperationRunner { _, _, request ->
            if (request.command == "probe-csms") pending.await()
            else JSONObject().put("result", "unexpected")
        }, this)
        model.bindCredentials { "https://remote.arthexis.com" to "test-token" }
        model.open("csms")
        runCurrent()
        assertTrue(model.current?.loading == true)
        model.close()
        model.open("notifications")
        pending.complete(JSONObject().put("result", "stale"))
        runCurrent()
        assertEquals("notifications", model.current?.id)
        assertNull(model.current?.output)
    }

    @Test fun changingCsmsViewDoesNotExecuteUntilInspect() = runTest {
        val calls = mutableListOf<String>()
        val model = ModuleOperationViewModel(OperationRunner { _, _, req ->
            calls.add(req.command.orEmpty())
            JSONObject().put("result", "read")
        }, this)
        model.bindCredentials { "https://remote.arthexis.com" to "test-token" }
        model.open("csms")
        runCurrent()
        assertEquals(listOf("probe-csms"), calls)
        model.selectCsmsView("events")
        runCurrent()
        assertEquals(listOf("probe-csms"), calls)
        model.inspectCsms("events")
        runCurrent()
        assertEquals(listOf("probe-csms", "csms-view"), calls)
    }

    @Test(expected = IllegalArgumentException::class)
    fun unknownModuleCannotBeActivated() {
        ModuleOperationViewModel().open("unrestricted")
    }
}
