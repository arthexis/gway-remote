package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class SimulatorPeerSelectionTest {
    @Test fun selectingTargetUpdatesUnifiedPanelInputsWithoutExecution() {
        val model = OperationViewModel()
        model.selectSimulatorPeer("192.0.2.25", "9000")
        val panel = model.panels.panels.single()
        assertEquals("simulator", panel.id)
        assertEquals("192.0.2.25", panel.inputs["host"])
        assertEquals("9000", panel.inputs["port"])
        assertFalse(panel.loading)
        assertNull(panel.output)
        assertNull(FeatureRegistry.get("simulator-discover"))
        assertNull(FeatureRegistry.get("simulator-start"))
    }

    @Test fun startStillRequiresConfirmation() {
        assertFalse(PanelExecution.canRun("simulator-start", true, false, true))
        assertTrue(PanelExecution.canRun("simulator-start", true, true, true))
    }
}
