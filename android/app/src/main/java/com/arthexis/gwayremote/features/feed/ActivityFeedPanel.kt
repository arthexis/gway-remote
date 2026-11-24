package com.arthexis.gwayremote.features.feed

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.arthexis.gwayremote.ui.components.ModuleActions
import com.arthexis.gwayremote.ui.components.ModuleNotice
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun FeedCredentialSettings(current: String, onSave: (String) -> Unit) {
    var draft by remember(current) { mutableStateOf("") }
    var feedback by remember(current) { mutableStateOf("") }
    Text("Activity Feed", style = MaterialTheme.typography.titleMedium)
    Text(if (current.isBlank()) "Sin credencial de lectura" else "Credencial de lectura configurada")
    Text("Usa un Bearer gway:read de Watchtower; no el token de operaciones.")
    OutlinedTextField(draft, { draft = it }, label = { Text("Bearer de lectura") },
        visualTransformation = PasswordVisualTransformation(), singleLine = true,
        modifier = Modifier.fillMaxWidth())
    ModuleActions {
        Button(onClick = {
            if (validFeedToken(draft.trim())) {
                try { onSave(draft.trim()); draft = ""; feedback = "Credencial guardada" }
                catch (_: Exception) { feedback = "No se pudo guardar la credencial" }
            } else feedback = "Formato de credencial inválido"
        }, enabled = draft.isNotBlank()) { Text("Guardar acceso al feed") }
        if (current.isNotBlank()) OutlinedButton(onClick = {
            try { onSave(""); draft = ""; feedback = "Acceso eliminado" }
            catch (_: Exception) { feedback = "No se pudo eliminar el acceso" }
        }) { Text("Eliminar acceso al feed") }
    }
    ModuleNotice(feedback)
}

@Composable
internal fun ActivityFeedPanel(token: String, onOpenSettings: () -> Unit, onNavigate: (String) -> Unit) {
    val context = LocalContext.current
    val cache = remember(context) { FeedCache(context.applicationContext) }
    val repository = remember { FeedRepository() }
    val scope = rememberCoroutineScope()
    var state by remember(token) { mutableStateOf(FeedState()) }
    var category by remember(token) { mutableStateOf<String?>(null) }
    var busy by remember(token) { mutableStateOf(validFeedToken(token)) }
    var offline by remember(token) { mutableStateOf(false) }
    var notice by remember(token) { mutableStateOf<String?>(null) }

    suspend fun refresh(fresh: Boolean) {
        if (!validFeedToken(token) || busy) return
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
                withContext(Dispatchers.IO) { cache.clear() }
                notice = if (e.status in setOf(401, 403)) "Acceso al feed no autorizado"
                    else "Activity Feed aún no habilitado"
            } else {
                val now = System.currentTimeMillis()
                if (state.savedAt !in (now - CACHE_AGE_MS)..now) {
                    state = FeedState()
                    withContext(Dispatchers.IO) { cache.clear() }
                }
                offline = state.items.isNotEmpty()
                notice = if (offline) "Sin conexión · mostrando historial guardado" else "Feed no disponible"
            }
        } finally { busy = false }
    }

    LaunchedEffect(token) {
        if (validFeedToken(token)) {
            val saved = withContext(Dispatchers.IO) { cache.read(token) }
            if (saved != null) { state = saved; offline = true }
            busy = false
            refresh(true)
        }
    }
    if (!validFeedToken(token)) {
        Text("Activity Feed", style = MaterialTheme.typography.titleMedium)
        ModuleNotice("Configura acceso de lectura para ver la actividad.")
        OutlinedButton(onClick = onOpenSettings) { Text("Configurar feed") }
    } else {
        FeedContent(state, category, busy, offline, notice,
            onCategory = { category = it },
            onRefresh = { scope.launch { refresh(true) } },
            onMore = { scope.launch { refresh(false) } },
            onRead = { seq ->
                state = state.mark(seq)
                val snapshot = state
                // Atomic write on the UI thread preserves ordering with subsequent marks.
                runCatching { cache.write(token, snapshot) }
            },
            onNavigate = onNavigate,
            onLink = { link ->
                safeFeedLink(link)?.let {
                    try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it))) }
                    catch (_: Exception) { notice = "No se pudo abrir el enlace" }
                }
            })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun FeedContent(state: FeedState, category: String?, busy: Boolean, offline: Boolean,
                         notice: String?, onCategory: (String?) -> Unit, onRefresh: () -> Unit,
                         onMore: () -> Unit, onRead: (Long) -> Unit,
                         onNavigate: (String) -> Unit, onLink: (String) -> Unit) {
    HorizontalDivider()
    Text("Activity Feed", style = MaterialTheme.typography.titleLarge)
    Text("Actividad reciente · sin alertas", style = MaterialTheme.typography.bodySmall)
    ModuleActions {
        OutlinedButton(onClick = onRefresh, enabled = !busy) { Text("Actualizar actividad") }
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
                    if (item.seq !in state.read) Text("Sin leer", style = MaterialTheme.typography.labelMedium)
                    ModuleActions {
                        if (item.seq !in state.read) TextButton(enabled = !busy, onClick = { onRead(item.seq) }) { Text("Marcar leído") }
                        item.moduleId?.let { id -> TextButton(enabled = !busy, onClick = { onRead(item.seq); onNavigate(id) }) { Text("Abrir módulo") } }
                        item.url?.let { link -> TextButton(enabled = !busy, onClick = { onRead(item.seq); onLink(link) }) { Text("Abrir enlace") } }
                    }
                }
            }
        }
    }
    if (state.more) OutlinedButton(onClick = onMore, enabled = !busy) { Text("Cargar anteriores") }
    else if (state.items.size >= CACHE_LIMIT) Text("Límite de historial local alcanzado")
}
