package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class SimulatorPanelMigrationTest {
    @Test fun discoveryRemainsExplicitButHiddenFromPalette() {
        val spec = OperationRegistry.get("simulator-discover")!!
        assertEquals(ExecutionPolicy.EXPLICIT_INPUT, spec.policy)
        assertNull(FeatureRegistry.get(spec.id))
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("simulator")?.kind)
        assertFalse(OperationPanelState().open("simulator").shouldAutoRun)
        assertFalse(PanelExecution.canRun(spec.id, false, false, true))
        assertTrue(PanelExecution.canRun(spec.id, true, false, true))
    }

    @Test fun startAndStopRequireConfirmation() {
        for (id in listOf("simulator-start", "simulator-stop")) {
            assertNull(FeatureRegistry.get(id))
            assertEquals(ExecutionPolicy.CONFIRM, OperationRegistry.get(id)?.policy)
            assertFalse(PanelExecution.canRun(id, false, true, true))
            assertFalse(PanelExecution.canRun(id, true, false, true))
            assertTrue(PanelExecution.canRun(id, true, true, true))
        }
    }

    @Test fun unifiedSimulatorPanelCloseReopenRejectsStaleOutput() {
        var panels = OperationPanelState().open("simulator").state
            .input("simulator", "host", "192.0.2.1")
            .input("simulator", "port", "9000")
        panels = panels.start("simulator")
        val prior = panels.panels.single().revision
        panels = panels.close("simulator").open("simulator").state
        assertNull(panels.panels.single().inputs["host"])
        assertNull(panels.complete("simulator", prior, "stale").panels.single().output)
        assertEquals(listOf("simulator"), panels.panels.map { it.id })
    }
}
