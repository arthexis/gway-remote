package com.arthexis.gwayremote.ui.shell

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModulePage
import com.arthexis.gwayremote.features.operations.OperationModulePage
import com.arthexis.gwayremote.features.benchmark.BenchmarkModule
import com.arthexis.gwayremote.features.deployments.DeploymentsPanel
import com.arthexis.gwayremote.features.githubhealth.GitHubHealthPanel
import com.arthexis.gwayremote.features.odoo.OdooQuotationsPanel
import com.arthexis.gwayremote.features.odoo.OdooOpportunitiesPanel
import com.arthexis.gwayremote.features.liturgia.LiturgiaPanel
import com.arthexis.gwayremote.features.liturgia.AuthenticatedLiturgiaSource
import com.arthexis.gwayremote.features.mcp.McpAccessPanel
import com.arthexis.gwayremote.features.updates.rememberAppUpdateController
import com.arthexis.gwayremote.features.feed.ActivityFeedPanel
import com.arthexis.gwayremote.features.feed.FeedCache

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

/** Shell owns navigation only. A module owns its own controls, state and output. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CompanionScreen(
    store: SecretStore,
    appearance: AppearanceMode = AppearanceMode.SYSTEM,
    onAppearanceChange: (AppearanceMode) -> Unit = {}
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val updates = rememberAppUpdateController()
    var settings by remember {
        mutableStateOf(CompanionSettingsState.initial(
            store.endpoint.ifBlank { "https://remote.arthexis.com" }, store.token
        ))
    }
    var feedConnection by remember { mutableStateOf(store.endpoint.ifBlank { "https://remote.arthexis.com" } to store.token) }
    LaunchedEffect(store) { store.removeLegacyFeedToken() }
    var selectedModuleId by rememberSaveable { mutableStateOf(ModuleRegistry.HOME) }
    var feedback by remember { mutableStateOf("") }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val snackbarHostState = remember { SnackbarHostState() }

    fun navigate(id: String) {
        val destination = ModuleRegistry.get(id)?.destination ?: return
        if (destination !is ModuleDestination.Screen) {
            // Future fixed external App Links never inherit GWay credentials.
            val intent = when (destination) {
                is ModuleDestination.HttpsLink ->
                    Intent(Intent.ACTION_VIEW, Uri.parse(destination.url))
                is ModuleDestination.AndroidAppLink ->
                    Intent(Intent.ACTION_VIEW, Uri.parse(destination.url)).setPackage(destination.packageName)
                else -> return
            }
            try {
                context.startActivity(intent)
            } catch (_: android.content.ActivityNotFoundException) {
                scope.launch { snackbarHostState.showSnackbar("La aplicación externa no está disponible") }
            } catch (_: SecurityException) {
                scope.launch { snackbarHostState.showSnackbar("No se puede abrir este módulo externo") }
            }
        } else {
            selectedModuleId = id
            feedback = ""
        }
        scope.launch { drawerState.close() }
    }

    BackHandler(enabled = drawerState.isOpen || selectedModuleId != ModuleRegistry.HOME) {
        if (drawerState.isOpen) scope.launch { drawerState.close() }
        else navigate(ModuleRegistry.HOME)
    }

    val installedVersion = remember(context) {
        runCatching {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "unknown"
        }.getOrDefault("unknown")
    }
    val configuredHost = remember(settings.endpoint, settings.token) {
        if (settings.token.isBlank()) "pendiente de token"
        else runCatching { java.net.URI(settings.endpoint.trim()).host }.getOrNull()
            ?: "pendiente de configuración"
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModuleDrawerContent(
                selectedId = selectedModuleId,
                updateAvailable = updates.available != null,
                onSelect = ::navigate
            )
        }
    ) {
        Scaffold(
            modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding(),
            snackbarHost = { SnackbarHost(snackbarHostState) },
            topBar = {
                TopAppBar(
                    title = { Text(ModuleRegistry.get(selectedModuleId)?.label ?: "GWay Remote") },
                    navigationIcon = {
                        IconButton(
                            onClick = { scope.launch { drawerState.open() } },
                            modifier = Modifier.semantics {
                                contentDescription = "Abrir menú de módulos"
                            }
                        ) {
                            Icon(Icons.Filled.Menu, contentDescription = null)
                        }
                    }
                )
            }
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                key(selectedModuleId) {
                when (selectedModuleId) {
                    ModuleRegistry.HOME -> ModulePage {
                        ModuleHomePage(
                            installedVersion = installedVersion,
                            configuredEndpoint = configuredHost,
                            availableUpdate = updates.available,
                            updateStatus = updates.status,
                            updating = updates.running,
                            onOpenUpdate = { navigate("app-update") },
                            updatesEnabled = updates.updatesEnabled
                        )
                        key(feedConnection) {
                            ActivityFeedPanel(feedConnection.first, feedConnection.second,
                                onNavigate = ::navigate)
                        }
                    }
                    ModuleRegistry.SETTINGS -> ModulePage {
                        ModuleSettingsPage(
                            settings = settings,
                            appearance = appearance,
                            onAppearanceChange = onAppearanceChange,
                            onEndpointChange = { settings = settings.copy(endpoint = it) },
                            onTokenChange = { settings = settings.copy(token = it) },
                            onSave = {
                                try {
                                    ApiClient(settings.endpoint.trim(), settings.token)
                                    store.endpoint = settings.endpoint.trim()
                                    store.token = settings.token
                                    val next = store.endpoint to store.token
                                    if (feedConnection != next) FeedCache(context).clear()
                                    feedConnection = next
                                    settings = settings.saved()
                                    feedback = "Configuración guardada"
                                } catch (e: Exception) {
                                    feedback = e.message ?: "Configuración inválida"
                                }
                            },
                            feedback = feedback
                        )
                    }
                    "app-update" -> ModulePage {
                        ModuleUpdatePage(
                            update = updates.available,
                            updateStatus = updates.status,
                            updating = updates.running,
                            apkReady = updates.apkReady,
                            onCheck = updates.check,
                            onDownload = updates.download,
                            onInstall = updates.install,
                            updatesEnabled = updates.updatesEnabled
                        )
                    }
                    "benchmark" -> ModulePage {
                        BenchmarkModule(settings.endpoint, settings.token)
                    }
                    "odoo-opportunities" -> OdooOpportunitiesPanel(settings.endpoint, settings.token)
                    "liturgia" -> LiturgiaPanel(remember(settings.endpoint, settings.token) { AuthenticatedLiturgiaSource(settings.endpoint, settings.token) })
                    "odoo-quotations" -> OdooQuotationsPanel(settings.endpoint, settings.token)
                    "deployments" -> ModulePage {
                        DeploymentsPanel(settings.endpoint, settings.token)
                    }
                    "mcp-access" -> ModulePage {
                        McpAccessPanel(onClose = { navigate(ModuleRegistry.HOME) })
                    }
                    "github-health" -> ModulePage { GitHubHealthPanel(settings.endpoint, settings.token) }
                    "system", "csms", "notifications", "agent-ops" ->
                        OperationModulePage(selectedModuleId, settings.endpoint, settings.token)
                    else -> ModulePage {
                        Text("Módulo no disponible", color = MaterialTheme.colorScheme.error)
                    }
                }
                }
            }
        }
    }
}
