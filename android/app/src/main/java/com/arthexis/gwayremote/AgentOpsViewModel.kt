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
    fun assignments() = OperationRequest("/api/v1/execute", "codex-issues")
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
    var issues by mutableStateOf(listOf<JSONObject>())
        private set

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

    fun refreshAssignments() {
        if (issuesLoading) return
        issuesLoading = true
        viewModelScope.launch {
            try {
                val response = request(AgentOpsRequests.assignments())
                val entries = response.getJSONObject("result").getJSONArray("issues")
                issues = (0 until entries.length()).map { entries.getJSONObject(it) }
                issuesError = ""
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                issuesError = e.message ?: "Assignments unavailable"
            } finally {
                issuesLoading = false
            }
        }
    }
}
