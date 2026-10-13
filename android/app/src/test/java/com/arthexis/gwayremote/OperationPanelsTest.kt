package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class OperationPanelsTest {
    @Test fun openingIsUniqueAndNewestFirst() {
        val first = OperationPanelState().open("status")
        assertTrue(first.shouldAutoRun)
        val two = first.state.open("sound")
        assertFalse(two.shouldAutoRun)
        assertEquals(listOf("sound", "status"), two.state.panels.map { it.id })
        val duplicate = two.state.open("status")
        assertFalse(duplicate.shouldAutoRun)
        assertEquals(two.state, duplicate.state)
    }

    @Test fun eachPanelOwnsItsInputsAndResults() {
        var state = OperationPanelState().open("lcd").state.open("status").state
        state = state.input("lcd", "message", "hello").start("lcd")
        val token = state.panels.first { it.id == "lcd" }.revision
        state = state.complete("lcd", token, "sent")
        assertEquals("sent", state.panels.first { it.id == "lcd" }.output)
        assertEquals("hello", state.panels.first { it.id == "lcd" }.inputs["message"])
        assertNull(state.panels.first { it.id == "status" }.output)
        state = state.start("status")
        val statusToken = state.panels.first().revision
        state = state.fail("status", statusToken, "offline")
        assertEquals("offline", state.panels.first().error)
        assertEquals("sent", state.panels.last().output)
    }

    @Test fun closeReopenRejectsOldResult() {
        var state = OperationPanelState().open("status").state.start("status")
        val old = state.panels.single().revision
        state = state.close("status").open("status").state.start("status")
        val current = state.panels.single().revision
        assertNotEquals(old, current)
        assertTrue(state.complete("status", old, "obsolete").panels.single().loading)
        state = state.complete("status", current, "fresh")
        assertEquals("fresh", state.panels.single().output)
    }

    @Test fun reorderAndFilteredPaletteStayIndependent() {
        var state = OperationPanelState().open("status").state.open("sound").state.open("lcd").state
        state = state.move("status", 0)
        assertEquals(listOf("status", "lcd", "sound"), state.panels.map { it.id })
        assertFalse(state.unopened("audio").any { it.id == "sound" })
        assertEquals(3, state.panels.size)
        assertEquals(state, state.move("missing", 0))
    }

    @Test fun restoredPanelsDoNotAutoExecute() {
        val restored = OperationPanelState().restore(listOf("status", "sound", "status", "nonexistent"))
        assertEquals(listOf("status", "sound"), restored.panels.map { it.id })
        assertTrue(restored.panels.all { !it.loading && it.output == null })
    }

    @Test fun executionGateRequiresDeliberateMutations() {
        assertTrue(PanelExecution.canRun("status", false, false, true))
        assertFalse(PanelExecution.canRun("lcd", false, false, true))
        assertTrue(PanelExecution.canRun("lcd", true, false, true))
        assertFalse(PanelExecution.canRun("simulator-start", true, false, true))
        assertTrue(PanelExecution.canRun("simulator-start", true, true, true))
        assertFalse(PanelExecution.canRun("simulator-start", true, true, false))
        assertFalse(PanelExecution.canRun("unknown", true, true, true))
    }
}
