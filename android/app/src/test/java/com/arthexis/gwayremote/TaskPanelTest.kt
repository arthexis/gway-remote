package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class TaskPanelTest {
    @Test fun historyIsVisibleAndDetailRemainsAnExplicitInternalCommand() {
        assertEquals(FeatureKind.OPERATION, FeatureRegistry.get("tasks")?.kind)
        assertNull(FeatureRegistry.get("task-detail"))
        assertEquals(ExecutionPolicy.AUTO_READ, OperationRegistry.get("tasks")?.policy)
        assertEquals("codex-tasks", OperationRegistry.get("tasks")?.command)
        assertEquals(ExecutionPolicy.EXPLICIT_INPUT, OperationRegistry.get("task-detail")?.policy)
        assertEquals("codex-task", OperationRegistry.get("task-detail")?.command)
        assertTrue(OperationPanelState().open("tasks").shouldAutoRun)
        assertFalse(PanelExecution.canRun("task-detail", false, false, true))
        assertTrue(PanelExecution.canRun("task-detail", true, false, true))
    }

    @Test fun invalidTaskSelectionDoesNotCreateASeparatePanel() {
        val model = OperationViewModel()
        // Invalid IDs are rejected before credentials, execution or coroutine dispatch.
        model.inspectTask("invalid")
        assertTrue(model.panels.panels.isEmpty())
        assertNull(model.taskDetailSelection)
        assertFalse(model.taskDetailLoading)
    }

    @Test fun closingTasksClearsSelectionWithoutChangingTheHistoryContract() {
        val model = OperationViewModel()
        model.close("tasks")
        assertNull(model.taskDetailSelection)
        assertNull(model.taskDetail)
        assertNull(model.taskDetailError)
        assertFalse(model.taskDetailLoading)
        assertEquals("codex-tasks", OperationRequests.automatic("tasks")?.command)
    }
}
