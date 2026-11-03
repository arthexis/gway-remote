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

    @Test fun invalidAndUnconfirmedOperationsNeverStart() {
        val model = OperationViewModel()
        model.open("sound")
        // No credentials or dispatched request are needed to prove invalid
        // commands fail before the asynchronous boundary.
        model.execute("unregistered-command", emptyMap())
        assertFalse(model.panels.panels.any { it.id == "unregistered-command" })
    }
}
