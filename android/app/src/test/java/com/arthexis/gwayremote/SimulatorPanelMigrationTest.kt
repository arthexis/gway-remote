package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class SimulatorPanelMigrationTest {
    @Test fun startAndStopRequireConfirmation() {
        for (id in listOf("simulator-start", "simulator-stop")) {
            assertEquals(ExecutionPolicy.CONFIRM, OperationRegistry.get(id)?.policy)
            assertFalse(PanelExecution.canRun(id, false, true, true))
            assertFalse(PanelExecution.canRun(id, true, false, true))
            assertTrue(PanelExecution.canRun(id, true, true, true))
        }
    }

    @Test fun simulatorInputsAreIndependentAndCloseReopenIsSafe() {
        var panels = OperationPanelState().open("simulator-start").state
            .open("simulator-stop").state
        panels = panels.input("simulator-start", "host", "192.0.2.1")
            .input("simulator-start", "port", "9000")
        assertNull(panels.panels.first { it.id == "simulator-stop" }.inputs["host"])
        panels = panels.start("simulator-start")
        val prior = panels.panels.first { it.id == "simulator-start" }.revision
        panels = panels.close("simulator-start").open("simulator-start").state
        assertNull(panels.panels.first { it.id == "simulator-start" }.inputs["host"])
        assertNull(panels.complete("simulator-start", prior, "stale")
            .panels.first { it.id == "simulator-start" }.output)
    }
}
