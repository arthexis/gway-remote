package com.arthexis.gwayremote

/**
 * Presentation state for command execution and refresh results.
 * HTTP requests, exception handling and coroutine ownership remain in CompanionScreen.
 */
internal data class CompanionCommandState(
    val result: String = "Configure HTTPS endpoint and token",
    val commands: List<String> = emptyList(),
    val busy: Boolean = false
) {
    fun started() = copy(busy = true)
    fun completed() = copy(busy = false)
    fun displayed(value: String) = copy(result = value)
    fun listed(values: List<String>) = copy(commands = values)
    fun failed(message: String, clearCommands: Boolean) =
        copy(result = message, commands = if (clearCommands) emptyList() else commands)
}

/** Retain the existing ordering and wording of refresh failure aggregation. */
internal object CompanionRefreshSummary {
    fun message(failures: List<String>): String =
        if (failures.isEmpty()) "Refresh completed"
        else "Refresh partially failed: ${failures.joinToString("; ")}"
}
