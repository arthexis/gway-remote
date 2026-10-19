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
class OperationViewModel(
    private val runner: OperationRunner = ProductionOperationRunner,
    private val scopeOverride: kotlinx.coroutines.CoroutineScope? = null
) : ViewModel() {
    private val requestScope get() = scopeOverride ?: viewModelScope
    var panels by mutableStateOf(OperationPanelState())
        private set

    data class SystemCheck(val loading: Boolean = false, val output: String? = null, val error: String? = null)
    var apiHealth by mutableStateOf(SystemCheck())
        private set
    var systemStatus by mutableStateOf(SystemCheck())
        private set
    private var systemSession = 0L
    private var apiRevision = 0L
    private var statusRevision = 0L

    /** Run each read independently: one failure must not hide the other result. */
    fun refreshSystem(check: String? = null) {
        if (panels.panels.none { it.id == "system" }) return
        if (check != null && check !in setOf("api-health", "status")) return
        val session = systemSession
        val (endpoint, token) = credentials()
        for (id in listOf("api-health", "status").filter { check == null || it == check }) {
            val request = OperationRequests.automatic(id) ?: continue
            val revision = if (id == "api-health") ++apiRevision else ++statusRevision
            if (id == "api-health") apiHealth = apiHealth.copy(loading = true, error = null)
            else systemStatus = systemStatus.copy(loading = true, error = null)
            requestScope.launch {
                try {
                    val response = runner.execute(endpoint, token, request)
                    if (session == systemSession && panels.panels.any { it.id == "system" } &&
                        revision == (if (id == "api-health") apiRevision else statusRevision)) {
                        val result = SystemCheck(output = response.toString(2))
                        if (id == "api-health") apiHealth = result else systemStatus = result
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (session == systemSession && panels.panels.any { it.id == "system" } &&
                        revision == (if (id == "api-health") apiRevision else statusRevision)) {
                        val result = SystemCheck(error = e.message ?: "Connection failed")
                        if (id == "api-health") apiHealth = result else systemStatus = result
                    }
                }
            }
        }
    }

    var simulatorStatus by mutableStateOf("Not checked")
        private set

    fun open(id: String) {
        val result = panels.open(id)
        panels = result.state
        if (id == "system") { if (result.shouldAutoRun) refreshSystem() }
        else if (result.shouldAutoRun) refresh(id)
    }

    fun close(id: String) {
        panels = panels.close(id)
        if (id == "system") {
            systemSession++
            apiRevision++
            statusRevision++
            apiHealth = SystemCheck()
            systemStatus = SystemCheck()
        }
        if (id == "tasks") {
            taskDetailRequest++
            taskDetail = null
            taskDetailLoading = false
            taskDetailError = null
            taskDetailSelection = null
        }
    }
    fun move(id: String, index: Int) { panels = panels.move(id, index) }
    fun input(id: String, key: String, value: String) { panels = panels.input(id, key, value) }
    var taskDetail by mutableStateOf<String?>(null)
        private set
    var taskDetailLoading by mutableStateOf(false)
        private set
    var taskDetailError by mutableStateOf<String?>(null)
        private set
    var taskDetailSelection by mutableStateOf<String?>(null)
        private set
    private var taskDetailRequest = 0L

    fun inspectTask(taskId: String) {
        val request = OperationRequests.explicit("task-detail", mapOf("task_id" to taskId)) ?: return
        if (panels.panels.none { it.id == "tasks" }) return
        val selection = ++taskDetailRequest
        taskDetailSelection = taskId
        taskDetailLoading = true
        taskDetailError = null
        taskDetail = null
        val (endpoint, token) = credentials()
        requestScope.launch {
            try {
                val response = runner.execute(endpoint, token, request)
                if (selection == taskDetailRequest && panels.panels.any { it.id == "tasks" }) {
                    taskDetail = response.toString(2)
                    taskDetailLoading = false
                }
            } catch (e: CancellationException) {
                if (selection == taskDetailRequest) taskDetailLoading = false
                throw e
            } catch (e: Exception) {
                if (selection == taskDetailRequest && panels.panels.any { it.id == "tasks" }) {
                    taskDetailError = e.message ?: "Task inspection failed"
                    taskDetailLoading = false
                }
            }
        }
    }
    fun selectSimulatorPeer(host: String, port: String) {
        panels = panels.open("simulator").state
            .input("simulator", "host", host)
            .input("simulator", "port", port)
    }
    fun updateSimulatorStatus(response: JSONObject) {
        val detail = response.optJSONObject("result")
        simulatorStatus = "${detail?.optString("state") ?: "unknown"} — " +
            (detail?.optString("target") ?: "")
    }
    fun runConfirmedSimulator(command: String, args: JSONObject) {
        val operationId = if (command == "simulator-stop") "simulator-stop" else "simulator-start"
        val id = if (panels.panels.any { it.id == "simulator" }) "simulator" else operationId
        if (command !in setOf("simulator-start", "simulator-stop") ||
            !PanelExecution.canRun(operationId, true, true, true) ||
            panels.panels.none { it.id == id && !it.loading }) return
        panels = panels.start(id)
        val revision = panels.panels.first { it.id == id }.revision
        val (endpoint, token) = credentials()
        requestScope.launch {
            try {
                val response = runner.execute(endpoint, token,
                    OperationRequest("/api/v1/execute", command, argsToMap(args)))
                val current = panels.panels.any {
                    it.id == id && it.loading && it.revision == revision
                }
                panels = panels.complete(id, revision, response.toString(2))
                if (current) updateSimulatorStatus(response)
            } catch (e: CancellationException) {
                panels = panels.fail(id, revision, "Cancelled")
                throw e
            } catch (e: Exception) {
                panels = panels.fail(id, revision, e.message ?: "Simulator command failed")
            }
        }
    }
    /** Read-only actions share the same visible Simulator panel and stale-result guard. */
    fun simulatorRead(command: String, args: JSONObject = JSONObject()) {
        if (command !in setOf("simulator-status", "simulator-results", "simulator-discover")) return
        val id = "simulator"
        if (panels.panels.none { it.id == id && !it.loading }) return
        panels = panels.start(id)
        val revision = panels.panels.first { it.id == id }.revision
        val (endpoint, token) = credentials()
        requestScope.launch {
            try {
                val response = runner.execute(endpoint, token,
                    OperationRequest("/api/v1/execute", command, argsToMap(args)))
                val current = panels.panels.any { it.id == id && it.loading && it.revision == revision }
                panels = panels.complete(id, revision, response.toString(2))
                if (current && command == "simulator-status") updateSimulatorStatus(response)
            } catch (e: CancellationException) {
                panels = panels.fail(id, revision, "Cancelled")
                throw e
            } catch (e: Exception) {
                panels = panels.fail(id, revision, e.message ?: "Simulator query failed")
            }
        }
    }

    private fun argsToMap(args: JSONObject): Map<String, Any> =
        args.keys().asSequence().associateWith { args.get(it) }


    private var credentials: () -> Pair<String, String> = { "" to "" }

    /** Credentials are retrieved when a run begins, never retained in a request. */
    fun bindCredentials(provider: () -> Pair<String, String>) { credentials = provider }

    fun inspectCsms(view: String) {
        val request = OperationRequests.explicit("csms-view", mapOf("view" to view)) ?: return
        if (panels.panels.none { it.id == "csms" }) return
        run("csms", request, "CSMS inspection failed")
    }

    fun refresh(id: String) {
        if (id == "system") { refreshSystem(); return }
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
        requestScope.launch {
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
                } else runner.execute(endpoint, token, requireNotNull(request))
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
