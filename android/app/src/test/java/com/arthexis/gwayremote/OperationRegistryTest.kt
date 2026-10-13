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

    @Test fun readOnlyAutoExecutionOnly() {
        listOf("status", "csms", "simulator-status", "agent-assignments", "agent-ops").forEach {
            assertTrue(OperationRegistry.get(it)!!.autoExecuteOnOpen)
        }
        listOf("lcd", "sound", "benchmark", "simulator-start", "simulator-stop").forEach {
            assertFalse(OperationRegistry.get(it)!!.autoExecuteOnOpen)
        }
        assertTrue(OperationRegistry.get("simulator-start")!!.requiresConfirmation)
        assertTrue(OperationRegistry.get("simulator-stop")!!.requiresConfirmation)
        assertFalse(OperationRegistry.get("sound")!!.requiresConfirmation)
    }

    @Test fun filterMatchesNamesAndKeywordsWithoutChangingRegistry() {
        assertEquals("sound", OperationRegistry.search("audio").single().id)
        assertTrue(OperationRegistry.search("charging session").any { it.id == "simulator-start" })
        assertEquals(OperationRegistry.operations.size, OperationRegistry.search(" ").size)
        assertTrue(OperationRegistry.search("missing-feature").isEmpty())
        assertEquals("sound", OperationRegistry.get("sound")!!.id)
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
