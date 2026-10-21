package com.arthexis.gwayremote

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Fixed, reviewed Agent Ops commands. Never accept arbitrary command names from the UI. */
internal object AgentOpsRequests {
    fun observe(ref: String, at: String) = OperationRequest(
        "/api/v1/execute", "agent-observe", mapOf("ref" to ref, "at" to at))
    fun preview(ref: String) = OperationRequest(
        "/api/v1/execute", "agent-preview", mapOf("ref" to ref))
    fun send(ref: String, at: String) = OperationRequest(
        "/api/v1/execute", "agent-issue", mapOf("ref" to ref, "at" to at))
    fun assignments() = OperationRequest("/api/v1/execute", "agent-issues")
}

/**
 * All remote Agent Ops execution runs off the UI thread, independent of
 * recomposition. Clipboard integration remains in the composable.
 */
class AgentOpsViewModel : ViewModel() {
    private var credentials: () -> Pair<String, String> = { "" to "" }
    fun bindCredentials(provider: () -> Pair<String, String>) { credentials = provider }

    var observeLoading by mutableStateOf(false)
        private set
    var observeResult by mutableStateOf<String?>(null)
        private set
    var observeError by mutableStateOf<String?>(null)
        private set
    var sendLoading by mutableStateOf(false)
        private set
    var sendResult by mutableStateOf<String?>(null)
        private set
    var sendError by mutableStateOf<String?>(null)
        private set
    var issuesLoading by mutableStateOf(false)
        private set
    var issuesError by mutableStateOf("")
        private set
    var localAgent by mutableStateOf("")
        private set
    var issues by mutableStateOf(listOf<JSONObject>())
        private set

    fun reportAssignmentsError(message: String) { issuesError = message }

    private suspend fun request(intent: OperationRequest, timeoutMs: Int = 10000): JSONObject {
        val (endpoint, token) = credentials()
        return withContext(Dispatchers.IO) {
            ApiClient(endpoint.trim(), token).request(
                intent.path, intent.command, intent.jsonArgs(), timeoutMs)
        }
    }

    fun observe(ref: String, at: String) {
        if (observeLoading) return
        observeLoading = true
        observeResult = null
        observeError = null
        viewModelScope.launch {
            try {
                val response = request(AgentOpsRequests.observe(ref, at))
                observeResult = response.optJSONObject("result")
                    ?.optJSONObject("data")?.optString("state", "unknown") ?: "unknown"
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                observeError = e.message ?: "Observation unavailable"
            } finally {
                observeLoading = false
            }
        }
    }

    fun preview(ref: String, onPrompt: (String) -> Unit) {
        viewModelScope.launch {
            try {
                val response = request(AgentOpsRequests.preview(ref))
                val prompt = response.optJSONObject("result")?.optJSONObject("data")
                    ?.optString("prompt", "").orEmpty()
                if (prompt.isBlank()) throw IllegalStateException("Prompt preview unavailable")
                onPrompt(prompt)
                sendResult = "Prompt copied for $ref; no issue was submitted."
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                sendError = e.message ?: "Prompt preview unavailable"
            }
        }
    }

    fun send(ref: String, at: String) {
        if (sendLoading) return
        sendLoading = true
        observeResult = null
        observeError = null
        sendResult = null
        sendError = null
        viewModelScope.launch {
            try {
                val response = request(AgentOpsRequests.send(ref, at), timeoutMs = 30000)
                sendResult = response.optJSONObject("result")?.toString(2) ?: response.toString(2)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                sendError = e.message ?: "Agent submission unavailable"
            } finally {
                sendLoading = false
            }
        }
    }

    private var assignmentsRefreshPending = false

    fun refreshAssignments() {
        if (issuesLoading) {
            assignmentsRefreshPending = true
            return
        }
        issuesLoading = true
        viewModelScope.launch {
            try {
                val response = request(AgentOpsRequests.assignments(), timeoutMs = 30000)
                // Agent Ops is the canonical issue projection. Its CLI envelope
                // is {result: {data: {issues: [...]}}}, unlike legacy codex-issues.
                val result = response.getJSONObject("result")
                val data = result.getJSONObject("data")
                val entries = data.getJSONArray("issues")
                val fresh = (0 until entries.length()).map { entries.getJSONObject(it) }
                issues = fresh
                // This appliance currently targets gway-001. The issue endpoint
                // need not include an agent identity; preserve a valid one if it does.
                localAgent = data.optString("agent", "").lowercase()
                    .takeIf { Regex("^gway-[0-9]+$").matches(it) }
                    ?: localAgent.takeIf { Regex("^gway-[0-9]+$").matches(it) }
                    ?: "gway-001"
                issuesError = ""
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // Never display a stale issue as if its labels were just refreshed.
                issues = emptyList()
                issuesError = e.message ?: "Assignments unavailable"
            } finally {
                issuesLoading = false
                if (assignmentsRefreshPending) {
                    assignmentsRefreshPending = false
                    refreshAssignments()
                }
            }
        }
    }
}
