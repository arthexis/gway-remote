package com.arthexis.gwayremote.features.odoo

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.PersistableBundle
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.arthexis.gwayremote.ApiClient
import com.arthexis.gwayremote.ui.components.ModulePage
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleNotice
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

private fun copySensitive(context: Context, value: String) {
    val clip = ClipData.newPlainText("", value)
    clip.description.extras = PersistableBundle().apply {
        putBoolean("android.content.extra.IS_SENSITIVE", true)
    }
    context.getSystemService(ClipboardManager::class.java).setPrimaryClip(clip)
}

@Composable
internal fun OpportunityCopyDialog(
    opportunity: Opportunity,
    onDismiss: () -> Unit,
    onCopy: (String) -> Unit
) {
    var copied by remember(opportunity.id) { mutableIntStateOf(-1) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Copiar datos") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                opportunity.copyValues.forEachIndexed { index, value ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(value.ifBlank { "—" }, modifier = Modifier.weight(1f))
                        IconButton(enabled = value.isNotBlank(), onClick = {
                            onCopy(value)
                            copied = index
                        }, modifier = Modifier.testTag("opportunity-copy-$index")) {
                            Icon(Icons.Outlined.ContentCopy,
                                contentDescription = if (copied == index) "Copiado" else "Copiar línea ${index + 1}")
                        }
                    }
                    if (index < 4) HorizontalDivider()
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cerrar") } }
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OdooOpportunitiesPanel(
    endpoint: String,
    token: String,
    loadOpportunities: suspend (String, String, Int) -> JSONObject = { host, accessToken, page ->
        withContext(Dispatchers.IO) {
            ApiClient(host.trim(), accessToken).request("/api/v1/execute", "odoo-opportunities",
                JSONObject().put("page", page).put("limit", 20), timeoutMs = 40000)
        }
    }
) {
    val context = LocalContext.current
    var records by remember(endpoint, token) { mutableStateOf<List<Opportunity>>(emptyList()) }
    var page by remember(endpoint, token) { mutableIntStateOf(1) }
    var hasNext by remember(endpoint, token) { mutableStateOf(false) }
    var refresh by remember(endpoint, token) { mutableIntStateOf(0) }
    var loading by remember(endpoint, token) { mutableStateOf(true) }
    var error by remember(endpoint, token) { mutableStateOf("") }
    var linkError by remember(endpoint, token) { mutableStateOf("") }
    var selectedId by remember(endpoint, token) { mutableStateOf<Int?>(null) }

    LaunchedEffect(endpoint, token, page, refresh) {
        if (endpoint.isBlank() || token.isBlank()) {
            error = "Configura el acceso de GWay Remote."
            loading = false
            return@LaunchedEffect
        }
        loading = true
        try {
            val result = parseOpportunityPage(loadOpportunities(endpoint, token, page))
            records = result.rows
            hasNext = result.hasNext
            if (records.none { it.id == selectedId }) selectedId = null
            error = ""
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            error = if (records.isEmpty()) "Oportunidades no disponibles. Verifica el acceso a CRM."
                else "No se pudo actualizar. Se muestran los últimos datos recibidos."
        } finally { loading = false }
    }

    fun reload() {
        if (!loading) { loading = true; refresh++ }
    }
    fun changePage(next: Int) {
        if (!loading && next > 0) {
            selectedId = null
            loading = true
            records = emptyList()
            hasNext = false
            page = next
        }
    }

    PullToRefreshBox(isRefreshing = loading, onRefresh = ::reload,
        modifier = Modifier.fillMaxSize().testTag("odoo-opportunities-refresh")) {
        ModulePage {
            ModuleHeader("Oportunidades · Odoo", "Pendientes hasta enviar la cotización. Desliza hacia abajo para actualizar.")
            ModuleNotice(error, isError = true)
            ModuleNotice(linkError, isError = true)
            if (!loading && error.isEmpty() && records.isEmpty())
                Text("No hay oportunidades pendientes.")
            records.forEach { opportunity ->
                HorizontalDivider()
                Text(opportunity.customer.ifBlank { "Cliente pendiente" }, style = MaterialTheme.typography.titleMedium)
                Text(opportunity.copyValues[3].ifBlank { "Datos de solicitud incompletos" },
                    style = MaterialTheme.typography.bodyMedium)
                Text(listOfNotNull(opportunity.status, opportunity.quotationName).joinToString(" · "),
                    style = MaterialTheme.typography.labelMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { selectedId = opportunity.id }) { Text("Copiar datos") }
                    OutlinedButton(enabled = opportunity.consentUrl != null, onClick = {
                        val url = opportunity.consentUrl ?: return@OutlinedButton
                        try {
                            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                            linkError = ""
                        } catch (_: Exception) { linkError = "No se pudo abrir la carta." }
                    }) { Text("Consentimiento") }
                }
                if (opportunity.consentUrl == null)
                    Text("Carta no disponible", style = MaterialTheme.typography.labelSmall)
            }
            if (page > 1 || hasNext) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically) {
                    OutlinedButton(enabled = !loading && page > 1, onClick = { changePage(page - 1) }) { Text("Anterior") }
                    Text("Página $page")
                    OutlinedButton(enabled = !loading && hasNext, onClick = { changePage(page + 1) }) { Text("Siguiente") }
                }
            }
        }
    }
    records.firstOrNull { it.id == selectedId }?.let { opportunity ->
        OpportunityCopyDialog(opportunity, { selectedId = null }) { value -> copySensitive(context, value) }
    }
}
