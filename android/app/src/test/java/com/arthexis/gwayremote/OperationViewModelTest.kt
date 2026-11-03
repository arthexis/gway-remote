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

    @Test fun removedSimulatorOperationsCannotOpenOrExecute() {
        val model = OperationViewModel()
        val removed = listOf("simulator", "simulator-start", "simulator-stop",
            "simulator-status", "simulator-results", "simulator-discover")
        for (id in removed) {
            assertNull(OperationRegistry.get(id))
            assertFalse(PanelExecution.canRun(id, explicit = true, confirmed = true, inputsValid = true))
            try {
                model.open(id)
                fail("Removed operation $id must be rejected")
            } catch (_: IllegalArgumentException) {
                // No panel is created for a retired operation.
            }
        }
        assertTrue(model.panels.panels.isEmpty())
    }
}
