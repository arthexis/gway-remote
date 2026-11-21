package com.arthexis.gwayremote.features.operations

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModulePage
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleLoading
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModuleSectionTitle

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
    val operations: ModuleOperationViewModel = viewModel()
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
        onDispose { operations.close() }
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

    val panel = operations.current?.takeIf { it.id == id }
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
    val content: @Composable () -> Unit = {
        ModulePage {
            ModuleHeader(ModuleRegistry.get(id)?.label ?: id)
            if (panel == null) {
                ModuleLoading(true)
                return@ModulePage
            }
            ModuleLoading(panel.loading)
            ModuleNotice(panel.error, isError = true)
            when (id) {
                "system" -> ModuleSystemContent(
                    operations.apiHealth, operations.systemStatus, operations::refreshSystem
                )
                "csms" -> CsmsUnifiedPanel(
                    panel, operations::refresh, operations::inspectCsms,
                    operations.csmsView, operations::selectCsmsView
                )
                "notifications" -> ModuleNotificationsContent(
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
    if (id == "notifications") {
        content()
    } else {
        PullToRefreshBox(
            isRefreshing = refreshing, onRefresh = { refresh() },
            modifier = Modifier.fillMaxSize()
        ) { content() }
    }
}

/** Native System result view; no dependency on the legacy panel manager. */
@Composable
internal fun ModuleSystemContent(
    api: ModuleOperationViewModel.SystemCheck,
    status: ModuleOperationViewModel.SystemCheck,
    refresh: (String?) -> Unit
) {
    var selected by remember { mutableStateOf("status") }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedButton(onClick = { selected = "status" }) { Text("Status") }
        OutlinedButton(onClick = { selected = "api-health" }) { Text("API Health") }
    }
    val check = if (selected == "status") status else api
    ModuleSectionTitle(if (selected == "status") "System status" else "API health")
    ModuleLoading(check.loading)
    ModuleNotice(check.error, isError = true)
    check.output?.let { GenericResultRenderer(it) }
}

/** Sound/LCD request state lives in the active Notifications module only. */
@Composable
internal fun ModuleNotificationsContent(
    lcd: ModuleOperationViewModel.NotificationRun,
    sound: ModuleOperationViewModel.NotificationRun,
    motifs: List<String>,
    onInput: (String, String, String) -> Unit,
    onExecute: (String, Map<String, String>) -> Unit
) {
    var selected by remember { mutableStateOf("sound") }
    TabRow(selectedTabIndex = if (selected == "sound") 0 else 1) {
        Tab(selected = selected == "sound", onClick = { selected = "sound" },
            text = { Text("Sound") })
        Tab(selected = selected == "lcd", onClick = { selected = "lcd" },
            text = { Text("LCD message") })
    }
    val state = if (selected == "sound") sound else lcd
    val spec = requireNotNull(OperationRegistry.get(selected))
    PanelActions(spec, OperationPanel(selected, state.inputs, state.loading, state.output, state.error),
        onRefresh = {}, onInput = onInput, onExecute = onExecute, motifs = motifs)
    ModuleLoading(state.loading)
    ModuleNotice(state.error, isError = true)
    state.output?.let { GenericResultRenderer(it) }
}
