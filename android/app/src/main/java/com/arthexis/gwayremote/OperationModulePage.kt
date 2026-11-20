package com.arthexis.gwayremote

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Dedicated native operation destination. No palette, draggable panels,
 * open/close controls, shared response area or other module's state.
 * Existing OperationViewModel retains its validated command allowlist.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun OperationModulePage(id: String, endpoint: String, token: String) {
    require(id in setOf("system", "csms", "notifications", "agent-ops"))
    val context = LocalContext.current
    val operations: OperationViewModel = viewModel()
    val agent: AgentOpsViewModel = viewModel()
    operations.bindCredentials { endpoint to token }
    agent.bindCredentials { endpoint to token }

    var agentAssignmentsExpanded by remember { mutableStateOf(false) }
    var soundMotifs by remember { mutableStateOf(CompanionSoundMotifsState()) }

    LaunchedEffect(id) {
        // Opening performs only the existing AUTO_READ operation; never writes.
        operations.open(id)
    }
    DisposableEffect(id) {
        onDispose { operations.close(id) }
    }
    LaunchedEffect(id, endpoint, token) {
        if (id == "notifications" && endpoint.isNotBlank() && token.isNotBlank()) {
            try {
                val response = withContext(Dispatchers.IO) {
                    ApiClient(endpoint.trim(), token).request(
                        "/api/v1/execute", "sound-motifs", JSONObject())
                }
                soundMotifs = soundMotifs.loaded(response)
            } catch (_: Exception) {
                soundMotifs = soundMotifs.failed()
            }
        }
    }

    val panel = operations.panels.panels.firstOrNull { it.id == id }
    fun refresh() {
        when (id) {
            "system" -> operations.refreshSystem()
            "csms" -> operations.csmsView?.let(operations::inspectCsms) ?: operations.refresh("csms")
            "agent-ops" -> {
                operations.refresh("agent-ops")
                if (agentAssignmentsExpanded) agent.refreshAssignments()
            }
            // Notification requests are explicitly initiated; no auto replay.
        }
    }
    val refreshing = panel?.loading == true ||
        (id == "system" && (operations.apiHealth.loading || operations.systemStatus.loading))
    PullToRefreshBox(
        isRefreshing = refreshing, onRefresh = { refresh() },
        modifier = Modifier.fillMaxSize()
    ) {
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            if (panel == null) {
                LinearProgressIndicator(Modifier.fillMaxWidth())
                return@Column
            }
            if (panel.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            panel.error?.takeIf { it.isNotBlank() }?.let {
                Text(it, color = MaterialTheme.colorScheme.error)
            }
            when (id) {
                "system" -> SystemUnifiedPanel(
                    operations.apiHealth, operations.systemStatus, operations::refreshSystem
                )
                "csms" -> CsmsUnifiedPanel(
                    panel, operations::refresh, operations::inspectCsms,
                    operations.csmsView, operations::selectCsmsView
                )
                "notifications" -> NotificationsUnifiedPanel(
                    operations.lcdNotification, operations.soundNotification,
                    soundMotifs.available, operations::notificationInput,
                    operations::executeNotification
                )
                "agent-ops" -> {
                    AgentOpsPanel(
                        output = panel.output,
                        sending = agent.sendLoading,
                        sendResult = agent.sendResult,
                        sendError = agent.sendError,
                        onSend = agent::send,
                        onCopyPrompt = { ref ->
                            agent.preview(ref) { prompt ->
                                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                                clipboard.setPrimaryClip(ClipData.newPlainText("Agent issue prompt", prompt))
                            }
                        },
                        observing = agent.observeLoading,
                        observation = agent.observeResult,
                        observationError = agent.observeError,
                        onObserve = agent::observe
                    )
                    AgentAssignmentsSection(
                        issues = agent.issues,
                        localAgent = agent.localAgent,
                        loading = agent.issuesLoading,
                        error = agent.issuesError,
                        onRefresh = agent::refreshAssignments,
                        onError = agent::reportAssignmentsError,
                        expanded = agentAssignmentsExpanded,
                        onExpandedChange = { agentAssignmentsExpanded = it }
                    )
                }
            }
        }
    }
}
