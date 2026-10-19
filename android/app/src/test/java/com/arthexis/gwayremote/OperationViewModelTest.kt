package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class OperationViewModelTest {
    @Test fun openCloseReopenKeepsRevisionProtection() {
        val model = OperationViewModel()
        model.open("sound")
        model.input("sound", "sound", "notice")
        assertEquals("notice", model.panels.panels.single().inputs["sound"])
        model.close("sound")
        model.open("sound")
        assertTrue(model.panels.panels.single().inputs.isEmpty())
    }

    @Test fun taskSelectionDoesNotExecute() {
        val model = OperationViewModel()
        model.inspectTask("123")
        val panel = model.panels.panels.single()
        assertEquals("task-detail", panel.id)
        assertEquals("123", panel.inputs["task_id"])
        assertFalse(panel.loading)
    }

    @Test fun peerSelectionIsInputOnly() {
        val model = OperationViewModel()
        model.selectSimulatorPeer("192.0.2.10", "9000")
        val panel = model.panels.panels.single()
        assertEquals("simulator-start", panel.id)
        assertEquals("192.0.2.10", panel.inputs["host"])
        assertFalse(panel.loading)
    }

    @Test fun invalidAndUnconfirmedOperationsNeverStart() {
        val model = OperationViewModel()
        model.open("sound")
        // No credentials or dispatched request are needed to prove invalid
        // commands fail before the asynchronous boundary.
        model.execute("simulator-start", emptyMap())
        assertFalse(model.panels.panels.any { it.id == "simulator-start" })
    }
}
