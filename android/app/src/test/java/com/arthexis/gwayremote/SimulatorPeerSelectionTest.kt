package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class SimulatorPeerSelectionTest {
    @Test fun selectingTargetUpdatesStartInputsWithoutExecution() {
        val state = OperationPanelState().open("simulator-discover").state
        val selected = state.open("simulator-start").state
            .input("simulator-start", "host", "192.0.2.25")
            .input("simulator-start", "port", "9000")
        val start = selected.panels.first { it.id == "simulator-start" }
        assertEquals("192.0.2.25", start.inputs["host"])
        assertEquals("9000", start.inputs["port"])
        assertFalse(start.loading)
        assertFalse(start.output != null)
    }

    @Test fun startStillRequiresConfirmation() {
        assertFalse(PanelExecution.canRun("simulator-start", true, false, true))
        assertTrue(PanelExecution.canRun("simulator-start", true, true, true))
    }
}
