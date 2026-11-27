package com.arthexis.gwayremote.features.feed

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import com.arthexis.gwayremote.ui.components.ModuleActions
import com.arthexis.gwayremote.ui.components.ModuleNotice
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun ActivityFeedPanel(endpoint: String, token: String, onNavigate: (String) -> Unit) {
    val context = LocalContext.current
    val cache = remember(context, endpoint) { FeedCache(context.applicationContext, endpoint) }
    val repository = remember(context, endpoint) { FeedRepository(context.applicationContext, endpoint) }
    val isCanary = context.packageName == CANARY_PACKAGE
    val configured = !isCanary && validMobileFeedKey(token) && runCatching { mobileFeedOrigin(endpoint) }.isSuccess
    val scope = rememberCoroutineScope()
    var state by remember(endpoint, token) { mutableStateOf(FeedState()) }
    var category by remember(endpoint, token) { mutableStateOf<String?>(null) }
    var busy by remember(endpoint, token) { mutableStateOf(configured) }
    var offline by remember(endpoint, token) { mutableStateOf(false) }
    var notice by remember(endpoint, token) { mutableStateOf<String?>(null) }

    suspend fun refresh(fresh: Boolean) {
        if (!configured || busy) return
        if (!fresh && (!state.more || state.next == null)) return
        busy = true
        try {
            val page = repository.page(token, if (fresh) null else state.next)
            state = state.merge(page, fresh, System.currentTimeMillis())
            offline = false
            notice = null
            val snapshot = state
            withContext(Dispatchers.IO) { runCatching { cache.write(token, snapshot) } }
        } catch (e: CancellationException) { throw e }
        catch (e: Exception) {
            if (e is FeedHttpError && e.status in setOf(401, 403, 404, 405)) {
                state = FeedState()
                offline = false
                withContext(Dispatchers.IO) { cache.clear(token) }
                notice = if (e.status in setOf(401, 403)) "Acceso al feed no autorizado"
                    else "Activity Feed aún no habilitado"
            } else {
                val now = System.currentTimeMillis()
                if (state.savedAt !in (now - CACHE_AGE_MS)..now) {
                    state = FeedState()
                    withContext(Dispatchers.IO) { cache.clear(token) }
                }
                offline = state.items.isNotEmpty()
                notice = if (offline) "Sin conexión · mostrando historial guardado" else "Feed no disponible"
            }
        } finally { busy = false }
    }

    LaunchedEffect(endpoint, token) {
        if (configured) {
            val saved = withContext(Dispatchers.IO) { cache.read(token) }
            if (saved != null) { state = saved; offline = true }
            busy = false
            refresh(true)
        }
    }
    if (isCanary) Text("Activity Feed · CANARY (USB)", style = MaterialTheme.typography.labelMedium)
    if (!configured) {
        Text("Activity Feed", style = MaterialTheme.typography.titleMedium)
        ModuleNotice(if (isCanary) "Feed aislado: requiere prueba USB autorizada." else "Configura la API Key y el endpoint HTTPS desde el menú lateral.")
    } else {
        FeedContent(state, category, busy, offline, notice,
            onCategory = { category = it },
            onRefresh = { scope.launch { refresh(true) } },
            onMore = { scope.launch { refresh(false) } },
            onRead = { seq ->
                val snapshot = state.mark(seq)
                // Publish only after the atomic local write succeeds.
                if (runCatching { cache.write(token, snapshot) }.getOrDefault(false)) {
                    state = snapshot
                    notice = null
                } else {
                    notice = "No se pudo marcar como leído"
                }
            },
            allowExternalActions = !isCanary,
            onNavigate = onNavigate,
            onLink = { link ->
                safeFeedLink(link)?.let {
                    try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it))) }
                    catch (_: Exception) { notice = "No se pudo abrir el enlace" }
                }
            })
    }
}

@OptIn(ExperimentalLayoutApi::class, ExperimentalComposeUiApi::class)
@Composable
internal fun FeedContent(state: FeedState, category: String?, busy: Boolean, offline: Boolean,
                         notice: String?, onCategory: (String?) -> Unit, onRefresh: () -> Unit,
                         onMore: () -> Unit, onRead: (Long) -> Unit,
                         onNavigate: (String) -> Unit, onLink: (String) -> Unit,
                         allowExternalActions: Boolean = true) {
    HorizontalDivider()
    Text("Activity Feed", style = MaterialTheme.typography.titleLarge)
    Text("Actividad reciente · sin alertas", style = MaterialTheme.typography.bodySmall)
    ModuleActions {
        OutlinedButton(onClick = onRefresh, enabled = !busy,
            modifier = Modifier.testTag("rc-feed-refresh").semantics { testTagsAsResourceId = true }) { Text("Actualizar actividad") }
    }
    if (busy) LinearProgressIndicator(Modifier.fillMaxWidth())
    if (offline) Text("Historial offline", color = MaterialTheme.colorScheme.onSurfaceVariant)
    ModuleNotice(notice)
    val categories = (state.items.map { it.category } + listOfNotNull(category)).distinct().sorted()
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        FilterChip(selected = category == null, onClick = { onCategory(null) }, label = { Text("Todos") })
        categories.forEach { value ->
            FilterChip(selected = category == value, onClick = { onCategory(value) },
                label = { Text(value) })
        }
    }
    val visible = state.visible(category)
    if (visible.isEmpty() && !busy) Text("No hay actividad para mostrar")
    for (item in visible) {
        key(item.seq) {
            OutlinedCard(Modifier.fillMaxWidth().testTag("feed-item-${item.seq}")) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(item.title, style = MaterialTheme.typography.titleSmall)
                    Text(item.summary, style = MaterialTheme.typography.bodyMedium)
                    Text(listOf(item.category, item.severity, item.node, item.repository)
                        .filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                    Text(runCatching { java.time.Instant.parse(item.time).atZone(java.time.ZoneId.systemDefault())
                        .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")) }
                        .getOrDefault(item.time), style = MaterialTheme.typography.bodySmall)
                    ModuleActions {
                        TextButton(enabled = !busy, onClick = { onRead(item.seq) }) { Text("Marcar leído") }
                        if (allowExternalActions) item.moduleId?.let { id -> TextButton(enabled = !busy, onClick = { onRead(item.seq); onNavigate(id) }) { Text("Abrir módulo") } }
                        if (allowExternalActions) item.url?.let { link -> TextButton(enabled = !busy, onClick = { onRead(item.seq); onLink(link) }) { Text("Abrir enlace") } }
                    }
                }
            }
        }
    }
    if (state.more) OutlinedButton(onClick = onMore, enabled = !busy) { Text("Cargar anteriores") }
    else if (state.items.size >= CACHE_LIMIT) Text("Límite de historial local alcanzado")
}
