package com.arthexis.gwayremote

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Single active operation for a native module destination.
 *
 * Unlike the old multi-panel manager this never stores a list, positioning,
 * panel visibility or restoration. Request revisions and session IDs ensure
 * that navigating away cannot reattach an asynchronous response.
 */
class ModuleOperationViewModel(
    private val runner: OperationRunner = ProductionOperationRunner,
    private val scopeOverride: CoroutineScope? = null
) : ViewModel() {
    private val requestScope get() = scopeOverride ?: viewModelScope
    var current by mutableStateOf<OperationPanel?>(null)
        private set
    var csmsView by mutableStateOf<String?>(null)
        private set

    data class SystemCheck(
        val loading: Boolean = false,
        val output: String? = null,
        val error: String? = null
    )
    data class NotificationRun(
        val inputs: Map<String, String> = emptyMap(),
        val loading: Boolean = false,
        val output: String? = null,
        val error: String? = null
    )

    var apiHealth by mutableStateOf(SystemCheck())
        private set
    var systemStatus by mutableStateOf(SystemCheck())
        private set
    var lcdNotification by mutableStateOf(NotificationRun())
        private set
    var soundNotification by mutableStateOf(NotificationRun())
        private set

    private var credentials: () -> Pair<String, String> = { "" to "" }
    fun bindCredentials(provider: () -> Pair<String, String>) { credentials = provider }

    private var session = 0L
    private var revision = 0L
    private var apiRevision = 0L
    private var statusRevision = 0L
    private var lcdRevision = 0L
    private var soundRevision = 0L

    fun open(id: String) {
        require(id in setOf("system", "csms", "notifications", "agent-ops"))
        if (current?.id == id) return
        close()
        current = OperationPanel(id)
        when (id) {
            "system" -> refreshSystem()
            "csms", "agent-ops" -> refresh(id)
        }
    }

    fun close() {
        session++
        revision++
        apiRevision++
        statusRevision++
        lcdRevision++
        soundRevision++
        current = null
        csmsView = null
        apiHealth = SystemCheck()
        systemStatus = SystemCheck()
        lcdNotification = NotificationRun()
        soundNotification = NotificationRun()
    }

    private fun active(id: String): Boolean = current?.id == id
    private fun start(id: String): Long? {
        val old = current?.takeIf { it.id == id } ?: return null
        val next = ++revision
        current = old.copy(loading = true, output = null, error = null, revision = next)
        return next
    }
    private fun complete(id: String, requestRevision: Long, output: String) {
        val old = current ?: return
        if (old.id == id && old.loading && old.revision == requestRevision)
            current = old.copy(loading = false, output = output)
    }
    private fun fail(id: String, requestRevision: Long, error: String) {
        val old = current ?: return
        if (old.id == id && old.loading && old.revision == requestRevision)
            current = old.copy(loading = false, error = error)
    }

    /** API health and node status are separately revisioned read operations. */
    fun refreshSystem(check: String? = null) {
        if (!active("system") || (check != null && check !in setOf("api-health", "status"))) return
        val openedSession = session
        val (endpoint, token) = credentials()
        for (id in listOf("api-health", "status").filter { check == null || it == check }) {
            val request = OperationRequests.automatic(id) ?: continue
            val requestRevision = if (id == "api-health") ++apiRevision else ++statusRevision
            if (id == "api-health") apiHealth = apiHealth.copy(loading = true, error = null)
            else systemStatus = systemStatus.copy(loading = true, error = null)
            requestScope.launch {
                try {
                    val response = runner.execute(endpoint, token, request)
                    if (openedSession == session && active("system") &&
                        requestRevision == (if (id == "api-health") apiRevision else statusRevision)) {
                        val result = SystemCheck(output = response.toString(2))
                        if (id == "api-health") apiHealth = result else systemStatus = result
                    }
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    if (openedSession == session && active("system") &&
                        requestRevision == (if (id == "api-health") apiRevision else statusRevision)) {
                        val result = SystemCheck(error = e.message ?: "Connection failed")
                        if (id == "api-health") apiHealth = result else systemStatus = result
                    }
                }
            }
        }
    }

    fun selectCsmsView(view: String) {
        if (!active("csms") || view !in setOf("status", "chargers", "charge-points",
                "transactions", "events", "alerts", "rfid-report", "report")) return
        csmsView = view
        current = current?.copy(loading = false, output = null, error = null, revision = ++revision)
    }

    fun inspectCsms(view: String) {
        if (!active("csms")) return
        val request = OperationRequests.explicit("csms-view", mapOf("view" to view)) ?: return
        run("csms", request, "CSMS inspection failed")
    }

    fun refresh(id: String) {
        if (!active(id)) return
        if (id == "system") { refreshSystem(); return }
        val request = OperationRequests.automatic(id)
        if (request == null && id != "agent-ops") return
        run(id, request, "Connection failed")
    }

    private fun run(id: String, request: OperationRequest?, fallback: String) {
        val requestRevision = start(id) ?: return
        val openedSession = session
        val (endpoint, token) = credentials()
        requestScope.launch {
            try {
                val response = if (id == "agent-ops") {
                    withContext(Dispatchers.IO) {
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
                if (openedSession == session) complete(id, requestRevision, response.toString(2))
            } catch (e: CancellationException) {
                if (openedSession == session) fail(id, requestRevision, "Cancelled")
                throw e
            } catch (e: Exception) {
                if (openedSession == session) fail(id, requestRevision, e.message ?: fallback)
            }
        }
    }

    fun notificationInput(kind: String, key: String, value: String) {
        if (!active("notifications")) return
        when (kind) {
            "lcd" -> lcdNotification = lcdNotification.copy(inputs = lcdNotification.inputs + (key to value))
            "sound" -> soundNotification = soundNotification.copy(inputs = soundNotification.inputs + (key to value))
        }
    }

    fun executeNotification(kind: String, inputs: Map<String, String>) {
        if (!active("notifications") || kind !in setOf("lcd", "sound")) return
        val state = if (kind == "lcd") lcdNotification else soundNotification
        if (state.loading) return
        val request = OperationRequests.explicit(kind, inputs) ?: return
        val requestRevision = if (kind == "lcd") ++lcdRevision else ++soundRevision
        val openedSession = session
        val (endpoint, token) = credentials()
        if (kind == "lcd") lcdNotification = state.copy(loading = true, error = null, output = null)
        else soundNotification = state.copy(loading = true, error = null, output = null)
        requestScope.launch {
            try {
                val response = runner.execute(endpoint, token, request)
                if (openedSession == session && active("notifications") &&
                    requestRevision == (if (kind == "lcd") lcdRevision else soundRevision)) {
                    val next = (if (kind == "lcd") lcdNotification else soundNotification)
                        .copy(loading = false, output = response.toString(2))
                    if (kind == "lcd") lcdNotification = next else soundNotification = next
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (openedSession == session && active("notifications") &&
                    requestRevision == (if (kind == "lcd") lcdRevision else soundRevision)) {
                    val next = (if (kind == "lcd") lcdNotification else soundNotification)
                        .copy(loading = false, error = e.message ?: "Notification failed")
                    if (kind == "lcd") lcdNotification = next else soundNotification = next
                }
            }
        }
    }
}
