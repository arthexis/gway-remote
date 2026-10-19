package com.arthexis.gwayremote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Explicit endpoint + allowlisted operation intent, never an arbitrary command. */
data class OperationRequest(
    val path: String,
    val command: String? = null,
    val parameters: Map<String, Any> = emptyMap()
) {
    fun jsonArgs(): JSONObject = JSONObject().apply {
        parameters.forEach { (key, value) -> put(key, value) }
    }
}

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
        val args = mutableMapOf<String, Any>()
        when (id) {
            "lcd" -> {
                val duration = inputs["duration"]?.toIntOrNull() ?: 30
                if (duration <= 0) return null
                args["line1"] = inputs["line1"].orEmpty()
                args["line2"] = inputs["line2"].orEmpty()
                args["duration_seconds"] = duration
            }
            "simulator-discover" -> {
                val port = inputs["port"]?.toIntOrNull() ?: return null
                if (port !in 1..65535) return null
                args["port"] = port
                inputs["host"]?.trim()?.takeIf(String::isNotEmpty)?.let { args["host"] = it }
            }
            "task-detail" -> {
                val idValue = inputs["task_id"].orEmpty()
                if (!Regex("[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}").matches(idValue)) return null
                args["task_id"] = idValue
            }
            "csms-view" -> args["view"] = inputs["view"] ?: "status"
            "sound" -> {
                args["sound"] = inputs["sound"] ?: "notice"
                inputs["motif"]?.takeIf(String::isNotBlank)?.let { args["motif"] = it }
            }
            else -> return null
        }
        return spec.command?.let { OperationRequest("/api/v1/execute", it, args.toMap()) }
    }
}

/** One shared IO boundary for all panel requests; errors are handled by caller state. */
object OperationExecutor {
    suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject =
        withContext(Dispatchers.IO) {
            ApiClient(endpoint.trim(), token).request(request.path, request.command, request.jsonArgs())
        }
}

/** Injectable IO boundary. Visibility and execution policy remain enforced by request planners. */
fun interface OperationRunner {
    suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject
}

object ProductionOperationRunner : OperationRunner {
    override suspend fun execute(endpoint: String, token: String, request: OperationRequest): JSONObject =
        OperationExecutor.execute(endpoint, token, request)
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
