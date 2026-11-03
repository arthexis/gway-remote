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

    data class NotificationRun(
        val inputs: Map<String, String> = emptyMap(),
        val loading: Boolean = false,
        val output: String? = null,
        val error: String? = null
    )
    var lcdNotification by mutableStateOf(NotificationRun())
        private set
    var soundNotification by mutableStateOf(NotificationRun())
        private set
    private var notificationSession = 0L
    private var lcdNotificationRevision = 0L
    private var soundNotificationRevision = 0L

    fun notificationInput(kind: String, key: String, value: String) {
        if (panels.panels.none { it.id == "notifications" }) return
        when (kind) {
            "lcd" -> lcdNotification = lcdNotification.copy(inputs = lcdNotification.inputs + (key to value))
            "sound" -> soundNotification = soundNotification.copy(inputs = soundNotification.inputs + (key to value))
        }
    }

    fun executeNotification(kind: String, inputs: Map<String, String>) {
        if (panels.panels.none { it.id == "notifications" } || kind !in setOf("lcd", "sound")) return
        val state = if (kind == "lcd") lcdNotification else soundNotification
        if (state.loading) return
        val request = OperationRequests.explicit(kind, inputs) ?: return
        val revision = if (kind == "lcd") ++lcdNotificationRevision else ++soundNotificationRevision
        val session = notificationSession
        val (endpoint, token) = credentials()
        if (kind == "lcd") lcdNotification = state.copy(loading = true, error = null, output = null)
        else soundNotification = state.copy(loading = true, error = null, output = null)
        requestScope.launch {
            try {
                val response = runner.execute(endpoint, token, request)
                if (session == notificationSession && panels.panels.any { it.id == "notifications" } &&
                    revision == (if (kind == "lcd") lcdNotificationRevision else soundNotificationRevision)) {
                    val result = (if (kind == "lcd") lcdNotification else soundNotification)
                        .copy(loading = false, output = response.toString(2))
                    if (kind == "lcd") lcdNotification = result else soundNotification = result
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (session == notificationSession && panels.panels.any { it.id == "notifications" } &&
                    revision == (if (kind == "lcd") lcdNotificationRevision else soundNotificationRevision)) {
                    val result = (if (kind == "lcd") lcdNotification else soundNotification)
                        .copy(loading = false, error = e.message ?: "Notification failed")
                    if (kind == "lcd") lcdNotification = result else soundNotification = result
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

    /** The selected read-only CSMS view lives in the ViewModel, not Composable memory. */
    var csmsView by mutableStateOf<String?>(null)
        private set
    var simulatorReadView by mutableStateOf("simulator-status")
        private set

    fun selectCsmsView(view: String) {
        if (panels.panels.none { it.id == "csms" } || view !in setOf(
            "status", "chargers", "charge-points", "transactions", "events",
            "alerts", "rfid-report", "report"
        )) return
        csmsView = view
        // A new selection invalidates an older in-flight inspection response.
        panels = panels.start("csms")
        val revision = panels.panels.first { it.id == "csms" }.revision
        panels = panels.fail("csms", revision, "")
    }

    /** Dispatch only safe reads on currently opened panels. */
    fun refreshOpenPanels() {
        RefreshRegistry.targets(panels).forEach { target ->
            when (target.kind) {
                RefreshKind.SYSTEM -> if (!apiHealth.loading && !systemStatus.loading) refreshSystem()
                RefreshKind.CSMS -> {
                    if (panels.panels.firstOrNull { it.id == "csms" }?.loading == false) {
                        val view = csmsView
                        if (view == null) refresh("csms") else inspectCsms(view)
                    }
                }
                RefreshKind.STANDARD, RefreshKind.AGENT_OPS -> {
                    if (panels.panels.firstOrNull { it.id == target.panelId }?.loading == false)
                        refresh(target.panelId)
                }
                RefreshKind.SIMULATOR -> {
                    if (panels.panels.firstOrNull { it.id == "simulator" }?.loading == false)
                        simulatorRead(simulatorReadView)
                }
            }
        }
    }

    fun selectSimulatorRead(view: String) {
        if (panels.panels.any { it.id == "simulator" } && view in setOf("simulator-status", "simulator-results")) {
            simulatorReadView = view
        }
    }

    fun close(id: String) {
        panels = panels.close(id)
        if (id == "csms") csmsView = null
        if (id == "simulator") simulatorReadView = "simulator-status"
        if (id == "notifications") {
            notificationSession++
            lcdNotificationRevision++
            soundNotificationRevision++
            lcdNotification = NotificationRun()
            soundNotification = NotificationRun()
        }
        if (id == "system") {
            systemSession++
            apiRevision++
            statusRevision++
            apiHealth = SystemCheck()
            systemStatus = SystemCheck()
        }
    }
    fun move(id: String, index: Int) { panels = panels.move(id, index) }
    fun input(id: String, key: String, value: String) { panels = panels.input(id, key, value) }
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
        if (command in setOf("simulator-status", "simulator-results")) simulatorReadView = command
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
