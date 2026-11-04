package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class OperationRegistryTest {
    @Test fun uniqueStableIdsAndMetadata() {
        val items = OperationRegistry.operations
        assertEquals(items.size, items.map { it.id }.distinct().size)
        assertTrue(items.all { it.label.isNotBlank() && it.icon.isNotBlank() })
        assertNull(OperationRegistry.get("arbitrary-shell"))
    }

    @Test fun visibilityIsIndependentOfExecutionPolicy() {
        assertEquals(ExecutionPolicy.AUTO_READ, OperationRegistry.get("status")?.policy)
        assertEquals(ExecutionPolicy.EXPLICIT_INPUT, OperationRegistry.get("sound")?.policy)
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
        assertTrue(OperationRegistry.search("charger").any { it.id == "csms" })
        assertEquals(OperationRegistry.operations.size, OperationRegistry.search(" ").size)
        assertTrue(OperationRegistry.search("missing-feature").isEmpty())
    }

    @Test fun obsoleteTasksPanelIsNotAvailableButAgentOpsRemains() {
        assertNull(OperationRegistry.get("tasks"))
        assertNull(OperationRegistry.get("task-detail"))
        assertFalse(OperationRegistry.operations.any { it.label == "Tasks" || it.command in setOf("codex-tasks", "codex-task") })
        assertFalse(OperationRegistry.search("tasks").any { it.id == "tasks" })
    }

    @Test fun specializedPanelsReferenceOnlyRegisteredOperations() {
        for (spec in OperationRegistry.operations) {
            // Forces initialization of PanelContentRegistry: the physical device
            // crashed here when stale Tasks entries were still present.
            assertNotNull(PanelContentRegistry.kind(spec.id))
        }
        assertEquals(PanelContentKind.AGENT_OPS, PanelContentRegistry.kind("agent-ops"))
        assertEquals(PanelContentKind.GENERIC, PanelContentRegistry.kind("tasks"))
        assertEquals(PanelContentKind.GENERIC, PanelContentRegistry.kind("task-detail"))
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
