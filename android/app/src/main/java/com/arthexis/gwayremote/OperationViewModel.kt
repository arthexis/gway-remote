package com.arthexis.gwayremote

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Owns panel lifecycle and request execution across Activity recompositions.
 * Revision tokens ensure that a closed/reopened panel never receives stale data.
 */
class OperationViewModel : ViewModel() {
    var panels by mutableStateOf(OperationPanelState())
        private set

    var simulatorStatus by mutableStateOf("Not checked")
        private set

    fun open(id: String) {
        val result = panels.open(id)
        panels = result.state
        if (result.shouldAutoRun) refresh(id)
    }

    fun close(id: String) { panels = panels.close(id) }
    fun move(id: String, index: Int) { panels = panels.move(id, index) }
    fun input(id: String, key: String, value: String) { panels = panels.input(id, key, value) }

    private var credentials: () -> Pair<String, String> = { "" to "" }

    /** Credentials are retrieved when a run begins, never retained in a request. */
    fun bindCredentials(provider: () -> Pair<String, String>) { credentials = provider }

    fun refresh(id: String) {
        val request = OperationRequests.automatic(id)
        if (request == null && id != "agent-ops") return
        run(id, request, "Connection failed")
    }

    fun execute(id: String, inputs: Map<String, String>) {
        val request = OperationRequests.explicit(id, inputs) ?: return
        run(id, request, "Execution failed")
    }

    private fun run(id: String, request: OperationRequest?, errorMessage: String) {
        if (panels.panels.none { it.id == id }) return
        panels = panels.start(id)
        val revision = panels.panels.firstOrNull { it.id == id }?.revision ?: return
        val (endpoint, token) = credentials()
        viewModelScope.launch {
            try {
                val response = if (id == "agent-ops") {
                    kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                        val client = ApiClient(endpoint.trim(), token)
                        val merged = JSONObject()
                        for (command in listOf("agent-issues", "agent-status")) {
                            val key = if (command == "agent-issues") "issues" else "status"
                            try {
                                merged.put(key, client.request("/api/v1/execute", command).opt("result"))
                            } catch (e: Exception) {
                                merged.put(key + "_error", e.message ?: "Unavailable")
                            }
                        }
                        JSONObject().put("result", merged)
                    }
                } else OperationExecutor.execute(endpoint, token, requireNotNull(request))
                val current = panels.panels.any {
                    it.id == id && it.loading && it.revision == revision
                }
                panels = panels.complete(id, revision, response.toString(2))
                if (current && id == "simulator-status") {
                    val detail = response.optJSONObject("result")
                    simulatorStatus = if (detail == null) "unknown" else
                        "${detail.optString("state", "unknown")} — ${detail.optString("target", "")}"
                }
            } catch (e: CancellationException) {
                panels = panels.fail(id, revision, "Cancelled")
                throw e
            } catch (e: Exception) {
                panels = panels.fail(id, revision, e.message ?: errorMessage)
            }
        }
    }
}
