package com.arthexis.gwayremote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Explicit endpoint + allowlisted operation intent, never an arbitrary command. */
data class OperationRequest(val path: String, val command: String? = null, val args: JSONObject = JSONObject())

/**
 * Immutable request planning is separate from coroutine execution and the UI.
 * A null plan means no request may be dispatched.
 */
object OperationRequests {
    fun automatic(id: String): OperationRequest? {
        val spec = OperationRegistry.get(id) ?: return null
        if (!PanelExecution.canRun(id, explicit = false, confirmed = false, inputsValid = true)) return null
        return when (id) {
            "api-health" -> OperationRequest("/api/v1/health")
            "api-commands" -> OperationRequest("/api/v1/commands")
            "agent-ops" -> null // Multi-source read is intentionally handled separately.
            else -> spec.command?.let { OperationRequest("/api/v1/execute", it) }
        }
    }

    fun explicit(id: String, inputs: Map<String, String>, confirmed: Boolean = false): OperationRequest? {
        val spec = OperationRegistry.get(id) ?: return null
        if (!PanelExecution.canRun(id, explicit = true, confirmed = confirmed, inputsValid = true)) return null
        val args = JSONObject()
        when (id) {
            "lcd" -> {
                val duration = inputs["duration"]?.toIntOrNull() ?: 30
                if (duration <= 0) return null
                args.put("line1", inputs["line1"].orEmpty())
                args.put("line2", inputs["line2"].orEmpty())
                args.put("duration_seconds", duration)
            }
            "simulator-discover" -> {
                val port = inputs["port"]?.toIntOrNull() ?: return null
                if (port !in 1..65535) return null
                args.put("port", port)
                inputs["host"]?.trim()?.takeIf(String::isNotEmpty)?.let { args.put("host", it) }
            }
            "task-detail" -> {
                val idValue = inputs["task_id"].orEmpty()
                if (!Regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}").matches(idValue)) return null
                args.put("task_id", idValue)
            }
            "csms-view" -> args.put("view", inputs["view"] ?: "status")
            "sound" -> {
                args.put("sound", inputs["sound"] ?: "notice")
                inputs["motif"]?.takeIf(String::isNotBlank)?.let { args.put("motif", it) }
            }
            else -> return null
        }
        return spec.command?.let { OperationRequest("/api/v1/execute", it, args) }
    }
}

/** One shared IO boundary for all panel requests; errors are handled by caller state. */
object OperationExecutor {
    suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject =
        withContext(Dispatchers.IO) {
            ApiClient(endpoint.trim(), token).request(request.path, request.command, request.args)
        }
}

/** Lifecycle-safe reducer: stale completions are rejected by OperationPanelState. */
class PanelRunState(initial: OperationPanelState = OperationPanelState()) {
    var current: OperationPanelState = initial
        private set

    fun update(next: OperationPanelState) { current = next }
    fun start(id: String): Long? {
        current = current.start(id)
        return current.panels.firstOrNull { it.id == id && it.loading }?.revision
    }
    fun complete(id: String, revision: Long, payload: String) {
        current = current.complete(id, revision, payload)
    }
    fun fail(id: String, revision: Long, message: String) {
        current = current.fail(id, revision, message)
    }
}
