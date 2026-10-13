package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class TaskPanelTest {
    @Test fun historyLoadsAsReadOnlyAndDetailRequiresExplicitAction() {
        assertEquals(ExecutionPolicy.AUTO_READ, OperationRegistry.get("tasks")?.policy)
        assertEquals("codex-tasks", OperationRegistry.get("tasks")?.command)
        assertEquals(ExecutionPolicy.EXPLICIT_INPUT, OperationRegistry.get("task-detail")?.policy)
        assertEquals("codex-task", OperationRegistry.get("task-detail")?.command)
        assertTrue(OperationPanelState().open("tasks").shouldAutoRun)
        assertFalse(OperationPanelState().open("task-detail").shouldAutoRun)
    }

    @Test fun selectingTaskDoesNotExecuteOrCorruptList() {
        var state = OperationPanelState().open("tasks").state
        state = state.open("task-detail").state
            .input("task-detail", "task_id", "8fc71471-92b8-4202-bda1-3dc4fe348402")
        assertFalse(state.panels.first { it.id == "task-detail" }.loading)
        assertNull(state.panels.first { it.id == "tasks" }.output)
        assertFalse(PanelExecution.canRun("task-detail", false, false, true))
        assertTrue(PanelExecution.canRun("task-detail", true, false, true))
    }
}
