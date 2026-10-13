package com.arthexis.gwayremote

/**
 * UI-1: metadata and safety policy only. The existing UI remains the executor
 * until UI-2/3 introduce composable panels. No arbitrary backend commands.
 */
enum class ExecutionPolicy {
    /** Safe and parameterless: a future panel may run immediately on opening. */
    AUTO_READ,
    /** Input must be validated and Run explicitly pressed. */
    EXPLICIT_INPUT,
    /** Explicit Run and confirmation are both required. */
    CONFIRM
}

data class OperationSpec(
    val id: String,
    val label: String,
    val icon: String,
    val keywords: Set<String>,
    val policy: ExecutionPolicy,
    val command: String? = null
) {
    val autoExecuteOnOpen: Boolean get() = policy == ExecutionPolicy.AUTO_READ
    val requiresConfirmation: Boolean get() = policy == ExecutionPolicy.CONFIRM
}

/**
 * Stable UI identifiers are distinct from backend command names.
 * Do not register a mutating operation as AUTO_READ.
 * Agent Ops is intentionally omitted until the existing UI migration is complete.
 */
object OperationRegistry {
    val operations: List<OperationSpec> = listOf(
        OperationSpec("status", "Status", "monitor", setOf("health", "node", "connection"),
            ExecutionPolicy.AUTO_READ, "status-quick"),
        OperationSpec("csms", "CSMS", "plug", setOf("charger", "ocpp", "transactions"),
            ExecutionPolicy.AUTO_READ, "probe-csms"),
        OperationSpec("csms-view", "CSMS details", "file-text", setOf("events", "status", "diagnostics"),
            ExecutionPolicy.EXPLICIT_INPUT, "csms-view"),
        OperationSpec("simulator-status", "Simulator status", "activity", setOf("charging", "session", "state"),
            ExecutionPolicy.AUTO_READ, "simulator-status"),
        OperationSpec("simulator-discover", "Discover simulator", "search", setOf("network", "peers", "ethernet"),
            ExecutionPolicy.EXPLICIT_INPUT, "simulator-discover"),
        OperationSpec("simulator-start", "Start simulator", "play", setOf("charging", "session", "start"),
            ExecutionPolicy.CONFIRM, "simulator-start"),
        OperationSpec("simulator-stop", "Stop simulator", "square", setOf("charging", "session", "stop"),
            ExecutionPolicy.CONFIRM, "simulator-stop"),
        OperationSpec("simulator-results", "Simulator results", "clipboard-list", setOf("logs", "outcome", "history"),
            ExecutionPolicy.AUTO_READ, "simulator-results"),
        OperationSpec("benchmark", "Benchmark", "gauge", setOf("latency", "rtt", "speed"),
            ExecutionPolicy.EXPLICIT_INPUT),
        OperationSpec("lcd", "LCD message", "monitor", setOf("display", "text", "duration"),
            ExecutionPolicy.EXPLICIT_INPUT, "lcd-message"),
        OperationSpec("sound", "Sound", "volume-2", setOf("play", "audio", "alert"),
            ExecutionPolicy.EXPLICIT_INPUT, "sound-play"),
        OperationSpec("agent-assignments", "Agent assignments", "list-check", setOf("github", "issues", "codex"),
            ExecutionPolicy.AUTO_READ, "codex-issues")
    )

    private val byId = operations.associateBy(OperationSpec::id)

    init {
        require(byId.size == operations.size) { "Duplicate operation ID" }
        require(operations.all { it.id.matches(Regex("[a-z][a-z0-9-]*")) })
        require(operations.all { it.label.isNotBlank() && it.icon.isNotBlank() })
    }

    fun get(id: String): OperationSpec? = byId[id]

    /** Filters future unopened-operation palette, never the panel state itself. */
    fun search(query: String): List<OperationSpec> {
        val terms = query.trim().lowercase().split(Regex("\\s+")).filter(String::isNotEmpty)
        if (terms.isEmpty()) return operations
        return operations.filter { item ->
            val searchable = (listOf(item.label, item.id) + item.keywords).joinToString(" ").lowercase()
            terms.all(searchable::contains)
        }
    }
}
