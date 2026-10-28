package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class OperationRegistryTest {
    @Test fun uniqueStableIdsAndMetadata() {
        val items = OperationRegistry.operations
        assertEquals(items.size, items.map { it.id }.distinct().size)
        assertTrue(items.all { it.label.isNotBlank() && it.icon.isNotBlank() })
        assertNotNull(OperationRegistry.get("sound"))
        assertNull(OperationRegistry.get("arbitrary-shell"))
    }

    @Test fun visibilityIsIndependentOfExecutionPolicy() {
        assertEquals(OperationVisibility.PALETTE, OperationRegistry.get("simulator")?.visibility)
        assertEquals(OperationVisibility.INTERNAL, OperationRegistry.get("simulator-start")?.visibility)
        assertEquals(OperationVisibility.INTERNAL, OperationRegistry.get("simulator-status")?.visibility)
        assertEquals(ExecutionPolicy.CONFIRM, OperationRegistry.get("simulator-start")?.policy)
        assertEquals(ExecutionPolicy.AUTO_READ, OperationRegistry.get("simulator-status")?.policy)
        assertEquals(OperationVisibility.PALETTE, OperationSpec("example", "Example", "activity", emptySet(), ExecutionPolicy.EXPLICIT_INPUT).visibility)
    }

    @Test fun autoRunIsRestrictedToReadOnlyOperations() {
        OperationRegistry.operations.forEach { spec ->
            assertEquals(spec.policy == ExecutionPolicy.AUTO_READ, spec.autoExecuteOnOpen)
            assertEquals(spec.policy == ExecutionPolicy.CONFIRM, spec.requiresConfirmation)
            if (spec.policy != ExecutionPolicy.AUTO_READ) {
                assertFalse(PanelExecution.canRun(spec.id, false, false, true))
            }
        }
    }

    @Test fun filterMatchesNamesAndKeywordsWithoutChangingRegistry() {
        assertEquals(setOf("sound", "notifications"), OperationRegistry.search("audio").map { it.id }.toSet())
        assertTrue(OperationRegistry.search("charging session").any { it.id == "simulator-start" })
        assertEquals(OperationRegistry.operations.size, OperationRegistry.search(" ").size)
        assertTrue(OperationRegistry.search("missing-feature").isEmpty())
        assertEquals("sound", OperationRegistry.get("sound")!!.id)
    }

    @Test fun obsoleteTasksPanelIsNotAvailableButAgentOpsRemains() {
        assertNull(OperationRegistry.get("tasks"))
        assertNull(OperationRegistry.get("task-detail"))
        assertFalse(OperationRegistry.operations.any { it.label == "Tasks" || it.command in setOf("codex-tasks", "codex-task") })
        assertFalse(OperationRegistry.search("tasks").any { it.id == "tasks" })
        assertNotNull(OperationRegistry.get("agent-ops"))
        assertNotNull(OperationRegistry.get("agent-assignments"))
    }

    @Test fun agentOpsIsOneSafePanel() {
        assertEquals(1, OperationRegistry.operations.count { it.id == "agent-ops" })
        assertNull(OperationRegistry.get("agent-issues"))
        assertNull(OperationRegistry.get("agent-status"))
        assertTrue(OperationRegistry.get("agent-ops")!!.autoExecuteOnOpen)
    }

    @Test fun noAgentExecutionIsExposedPrematurely() {
        assertTrue(OperationRegistry.operations.none { it.command == "agent-issue" })
        assertTrue(OperationRegistry.operations.none { it.command == "shell" })
    }
}
