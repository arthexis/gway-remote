package com.arthexis.gwayremote.features.odoo

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModulePage
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleLoading
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModuleActions

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.ui.Alignment
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private data class QuotationSummary(
    val id: Int, val name: String, val customer: String, val date: String,
    val state: String, val amount: String, val suggestedPdfFilename: String?
)

internal fun localQuotationFilename(name: String, suggested: String?): String {
    val folio = Regex("^([A-Za-z]+[0-9]+)(?:\\s|$)").find(name)?.groupValues?.get(1)
    val candidate = suggested?.takeIf {
        folio != null && it.startsWith("Cotización $folio ") &&
            Regex("Cotización [A-Za-z]+[0-9]+ [A-Z]{1,16} - [A-Za-z][A-Za-z ]{0,30}\\.pdf").matches(it)
    }
    return candidate ?: name + ".pdf"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OdooQuotationsPanel(
    endpoint: String,
    token: String,
    loadQuotations: suspend (String, String, String, Int) -> JSONObject = { host, accessToken, query, page ->
        withContext(Dispatchers.IO) {
            ApiClient(host.trim(), accessToken).request("/api/v1/execute",
                "odoo-quotations", JSONObject().put("query", query)
                    .put("limit", 10).put("page", page), timeoutMs = 40000)
        }
    }
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var query by remember(endpoint, token) { mutableStateOf("") }
    var submittedQuery by remember(endpoint, token) { mutableStateOf("") }
    var page by remember(endpoint, token) { mutableIntStateOf(1) }
    var hasNext by remember(endpoint, token) { mutableStateOf(false) }
    var records by remember(endpoint, token) { mutableStateOf<List<QuotationSummary>>(emptyList()) }
    var loading by remember(endpoint, token) { mutableStateOf(false) }
    var downloading by remember(endpoint, token) { mutableStateOf(false) }
    var status by remember(endpoint, token) { mutableStateOf("") }
    var refresh by remember(endpoint, token) { mutableIntStateOf(0) }
    var pending by remember(endpoint, token) { mutableStateOf<QuotationSummary?>(null) }

    val picker = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/pdf")
    ) { uri: Uri? ->
        val selected = pending
        pending = null
        if (uri != null && selected != null) {
            downloading = true
            scope.launch {
                try {
                    val size = withContext(Dispatchers.IO) {
                        try {
                            val stream = context.contentResolver.openOutputStream(uri, "w")
                                ?: throw IllegalStateException("Cannot create PDF")
                            stream.use { OdooPdfTransfer.download(endpoint.trim(), token, selected.id,
                                selected.name, it) }
                        } catch (e: Exception) {
                            // Never leave a misleading partial PDF in Downloads.
                            runCatching { context.contentResolver.delete(uri, null, null) }
                            throw e
                        }
                    }
                    status = "PDF guardado ($size bytes)"
                } catch (e: Exception) {
                    status = "Descarga fallida: ${e.message ?: "Inténtalo nuevamente"}"
                } finally { downloading = false }
            }
        }
    }

    LaunchedEffect(endpoint, token, submittedQuery, page, refresh) {
        if (endpoint.isBlank() || token.isBlank()) {
            status = "Configura el endpoint HTTPS y el token de GWay Remote."
            loading = false
            return@LaunchedEffect
        }
        loading = true
        try {
            val requestQuery = submittedQuery
            val requestPage = page
            val response = loadQuotations(endpoint, token, requestQuery, requestPage)
            val result = response.getJSONObject("result")
            val rows = result.getJSONArray("quotations")
            val next = result.getBoolean("has_next")
            val loadedRecords = (0 until rows.length()).mapNotNull { index ->
                val row = rows.optJSONObject(index) ?: return@mapNotNull null
                val id = row.optInt("id")
                val name = row.optString("name")
                if (id <= 0 || name.isBlank()) return@mapNotNull null
                QuotationSummary(
                    id, name, row.optString("customer"), row.optString("date"),
                    row.optString("state"), "${row.opt("total")} ${row.optString("currency", "MXN")}",
                    row.opt("suggested_pdf_filename") as? String
                )
            }
            records = loadedRecords
            hasNext = next
            status = if (records.isEmpty()) "No hay cotizaciones para esta búsqueda." else ""
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            status = "No se pudieron cargar las cotizaciones: ${e.message ?: "Error de conexión"}"
        } finally { loading = false }
    }

    fun reloadVisible() {
        if (!loading && !downloading && pending == null) {
            loading = true
            refresh++
        }
    }

    fun changePage(newPage: Int, newQuery: String = submittedQuery) {
        if (loading || downloading || pending != null) return
        if (newPage != page || newQuery != submittedQuery) {
            records = emptyList()
            hasNext = false
        }
        submittedQuery = newQuery
        page = newPage
        loading = true
        refresh++
    }

    PullToRefreshBox(
        isRefreshing = loading,
        onRefresh = { reloadVisible() },
        modifier = Modifier.fillMaxSize().testTag("odoo-quotations-refresh")
    ) {
        ModulePage {
        ModuleHeader("Cotizaciones · Odoo", "Busca por folio o cliente y guarda el PDF oficial. Desliza hacia abajo para actualizar.")
        OutlinedTextField(
            value = query, onValueChange = { query = it.take(80) },
            label = { Text("Folio o cliente") }, singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        ModuleActions {
            Button(onClick = {
                changePage(1, query.trim())
            }, enabled = !loading && !downloading) {
                Text(if (loading) "Buscando…" else "Buscar")
            }
            OutlinedButton(onClick = {
                query = ""
                changePage(1, "")
            }, enabled = !loading && !downloading) {
                Text("Recientes")
            }
        }
        ModuleLoading(downloading)
        ModuleNotice(status, isError = status.startsWith("No se pudieron") || status.startsWith("Descarga fallida") || status.startsWith("Configura"))
        records.forEach { row ->
            HorizontalDivider()
            Row(
                modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.dp)
                ) {
                    Text(
                        row.name, style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1, overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        row.customer, style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                        maxLines = 1, overflow = TextOverflow.Ellipsis
                    )
                    Text(
                        "${row.amount} · ${row.date.take(10)}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1, overflow = TextOverflow.Ellipsis
                    )
                }
                IconButton(
                    onClick = {
                        pending = row
                        picker.launch(localQuotationFilename(row.name, row.suggestedPdfFilename))
                    },
                    enabled = !downloading && !loading && pending == null,
                    modifier = Modifier.size(48.dp)
                ) {
                    Icon(
                        imageVector = Icons.Outlined.FileDownload,
                        contentDescription = "Descargar PDF de ${row.name}",
                        tint = MaterialTheme.colorScheme.primary
                    )
                }
            }
        }
        if (!loading && (records.isNotEmpty() || page > 1)) {
            HorizontalDivider()
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                OutlinedButton(
                    onClick = { changePage(page - 1) },
                    enabled = page > 1 && !downloading
                ) { Text("Anterior") }
                Text("Página $page", style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurface)
                OutlinedButton(
                    onClick = { changePage(page + 1) },
                    enabled = hasNext && !downloading
                ) { Text("Siguiente") }
            }
        }
    }
}
}
