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

    @Test fun removedTasksAreNotRegisteredOrOpened() {
        val model = OperationViewModel()
        assertNull(OperationRegistry.get("tasks"))
        assertNull(OperationRegistry.get("task-detail"))
        for (removed in listOf("tasks", "task-detail")) {
            try {
                model.open(removed)
                fail("Removed operation $removed must be rejected")
            } catch (_: IllegalArgumentException) {
                // The registry correctly rejects unknown operations.
            }
        }
        assertTrue(model.panels.panels.isEmpty())
    }

    @Test fun peerSelectionIsInputOnly() {
        val model = OperationViewModel()
        model.selectSimulatorPeer("192.0.2.10", "9000")
        val panel = model.panels.panels.single()
        assertEquals("simulator", panel.id)
        assertEquals("192.0.2.10", panel.inputs["host"])
        assertEquals("9000", panel.inputs["port"])
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
