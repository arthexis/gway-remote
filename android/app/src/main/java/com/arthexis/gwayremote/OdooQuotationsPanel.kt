package com.arthexis.gwayremote

import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

private data class QuotationSummary(
    val id: Int, val name: String, val customer: String, val date: String,
    val state: String, val amount: String
)

@Composable
fun OdooQuotationsPanel(endpoint: String, token: String) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var records by remember { mutableStateOf<List<QuotationSummary>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var downloading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("") }
    var refresh by remember { mutableIntStateOf(0) }
    var pending by remember { mutableStateOf<QuotationSummary?>(null) }

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
                    status = "PDF guardado: ${selected.name}.pdf ($size bytes)"
                } catch (e: Exception) {
                    status = "Descarga fallida: ${e.message ?: "Inténtalo nuevamente"}"
                } finally { downloading = false }
            }
        }
    }

    LaunchedEffect(endpoint, token, refresh) {
        if (endpoint.isBlank() || token.isBlank()) {
            status = "Configura el endpoint HTTPS y el token de GWay Remote."
            return@LaunchedEffect
        }
        loading = true
        try {
            val response = withContext(Dispatchers.IO) {
                ApiClient(endpoint.trim(), token).request("/api/v1/execute",
                    "odoo-quotations", JSONObject().put("query", query.trim()).put("limit", 30),
                    timeoutMs = 40000)
            }
            val rows = response.getJSONObject("result").getJSONArray("quotations")
            records = (0 until rows.length()).mapNotNull { index ->
                val row = rows.optJSONObject(index) ?: return@mapNotNull null
                val id = row.optInt("id")
                val name = row.optString("name")
                if (id <= 0 || name.isBlank()) return@mapNotNull null
                QuotationSummary(
                    id, name, row.optString("customer"), row.optString("date"),
                    row.optString("state"), "${row.opt("total")} ${row.optString("currency", "MXN")}"
                )
            }
            status = if (records.isEmpty()) "No hay cotizaciones para esta búsqueda." else
                "${records.size} cotizaciones encontradas"
        } catch (e: Exception) {
            records = emptyList()
            status = "No se pudieron cargar las cotizaciones: ${e.message ?: "Error de conexión"}"
        } finally { loading = false }
    }

    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Cotizaciones · Odoo", style = MaterialTheme.typography.titleMedium)
        Text("Busca por folio o cliente y guarda el PDF oficial con su nombre en Odoo.",
            style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(
            value = query, onValueChange = { query = it.take(80) },
            label = { Text("Folio o cliente") }, singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { refresh++ }, enabled = !loading && !downloading) {
                Text(if (loading) "Buscando…" else "Buscar")
            }
            OutlinedButton(onClick = { query = ""; refresh++ }, enabled = !loading && !downloading) {
                Text("Recientes")
            }
        }
        if (loading || downloading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (status.isNotBlank()) Text(status, style = MaterialTheme.typography.bodySmall)
        records.forEach { row ->
            HorizontalDivider()
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(row.name, style = MaterialTheme.typography.titleSmall)
                Text("${row.customer} · ${row.amount}", style = MaterialTheme.typography.bodySmall)
                Text("${row.state} · ${row.date.take(10)}",
                    style = MaterialTheme.typography.labelSmall)
                OutlinedButton(
                    onClick = {
                        pending = row
                        picker.launch(row.name + ".pdf")
                    }, enabled = !downloading && !loading
                ) { Text("Descargar PDF") }
            }
        }
    }
}
