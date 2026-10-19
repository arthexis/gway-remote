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

/** Palette visibility does not grant execution permission. */
enum class OperationVisibility { PALETTE, INTERNAL }

data class OperationSpec(
    val id: String,
    val label: String,
    val icon: String,
    val keywords: Set<String>,
    val policy: ExecutionPolicy,
    val command: String? = null,
    val visibility: OperationVisibility = OperationVisibility.PALETTE
) {
    val autoExecuteOnOpen: Boolean get() = policy == ExecutionPolicy.AUTO_READ
    val requiresConfirmation: Boolean get() = policy == ExecutionPolicy.CONFIRM
}

/**
 * Stable UI identifiers are distinct from backend command names.
 * Do not register a mutating operation as AUTO_READ.
 * Agent Ops groups read-only CLI operations in one panel.
 */
object OperationRegistry {
    val operations: List<OperationSpec> = listOf(
        OperationSpec("system", "System", "monitor",
            setOf("api", "health", "status", "connection", "node"), ExecutionPolicy.AUTO_READ),
        OperationSpec("api-health", "API health", "heart-pulse", setOf("test", "connection", "health"),
            ExecutionPolicy.AUTO_READ, visibility = OperationVisibility.INTERNAL),
        OperationSpec("status", "Status", "monitor", setOf("health", "node", "connection"),
            ExecutionPolicy.AUTO_READ, "status-quick", visibility = OperationVisibility.INTERNAL),
        OperationSpec("csms", "CSMS", "plug", setOf("charger", "ocpp", "transactions"),
            ExecutionPolicy.AUTO_READ, "probe-csms"),
        OperationSpec("csms-view", "CSMS details", "file-text", setOf("events", "status", "diagnostics"),
            ExecutionPolicy.EXPLICIT_INPUT, "csms-view", visibility = OperationVisibility.INTERNAL),
        OperationSpec("simulator", "Simulator", "activity", setOf("simulation", "discover", "start", "stop", "results", "status"),
            ExecutionPolicy.EXPLICIT_INPUT),
        OperationSpec("simulator-status", "Simulator status", "activity", setOf("charging", "session", "state"),
            ExecutionPolicy.AUTO_READ, "simulator-status", visibility = OperationVisibility.INTERNAL),
        OperationSpec("simulator-discover", "Discover simulator", "search", setOf("network", "peers", "ethernet"),
            ExecutionPolicy.EXPLICIT_INPUT, "simulator-discover", visibility = OperationVisibility.INTERNAL),
        OperationSpec("simulator-start", "Start simulator", "play", setOf("charging", "session", "start"),
            ExecutionPolicy.CONFIRM, "simulator-start", visibility = OperationVisibility.INTERNAL),
        OperationSpec("simulator-stop", "Stop simulator", "square", setOf("charging", "session", "stop"),
            ExecutionPolicy.CONFIRM, "simulator-stop", visibility = OperationVisibility.INTERNAL),
        OperationSpec("simulator-results", "Simulator results", "clipboard-list", setOf("logs", "outcome", "history"),
            ExecutionPolicy.AUTO_READ, "simulator-results", visibility = OperationVisibility.INTERNAL),
        OperationSpec("benchmark", "Benchmark", "gauge", setOf("latency", "rtt", "speed"),
            ExecutionPolicy.EXPLICIT_INPUT),
        OperationSpec("lcd", "LCD message", "monitor", setOf("display", "text", "duration"),
            ExecutionPolicy.EXPLICIT_INPUT, "lcd-message"),
        OperationSpec("sound", "Sound", "volume-2", setOf("play", "audio", "alert"),
            ExecutionPolicy.EXPLICIT_INPUT, "sound-play"),
        OperationSpec("agent-ops", "Assigned Issues", "list-checks",
            setOf("agent", "issues", "status", "github", "budgets", "five-hour", "weekly"),
            ExecutionPolicy.AUTO_READ),
        OperationSpec("tasks", "Tasks", "list-todo", setOf("codex", "jobs", "executions", "history", "detail", "task"),
            ExecutionPolicy.AUTO_READ, "codex-tasks"),
        OperationSpec("task-detail", "Task detail", "clipboard-check", setOf("task", "result", "execution", "id"),
            ExecutionPolicy.EXPLICIT_INPUT, "codex-task", visibility = OperationVisibility.INTERNAL),
        OperationSpec("agent-assignments", "Agent assignments", "list-check", setOf("github", "issues", "codex"),
            ExecutionPolicy.AUTO_READ, "codex-issues", visibility = OperationVisibility.INTERNAL)
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
