package com.arthexis.gwayremote.features.liturgia

import android.content.Intent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.arthexis.gwayremote.ui.components.*
import kotlinx.coroutines.CancellationException
import java.time.LocalDate
import java.time.ZoneId

private data class Load<T>(val value: T? = null, val loading: Boolean = false, val error: Boolean = false)
private suspend fun <T> load(block: suspend () -> T): Load<T> = try {
    Load(value = block())
} catch (e: CancellationException) {
    throw e
} catch (_: Exception) {
    // Do not expose raw server errors or potentially protected text in logs.
    Load(error = true)
}

private data class VerseRequest(val passage: Passage, val offset: Int = 0)
private data class SearchPageRequest(val query: SearchRequest, val offset: Int = 0)

/** A dedicated module view; the shell will register it after transport acceptance. */
@Composable
internal fun LiturgiaPanel(source: LiturgiaSource, libraryOverride: LiturgiaLocalLibrary? = null) {
    val context = LocalContext.current
    val library = remember(context, libraryOverride) { libraryOverride ?: LiturgiaLocalLibrary(context) }
    var bookmarks by remember(library) { mutableStateOf(library.bookmarks()) }
    var history by remember(library) { mutableStateOf(library.history()) }
    var readingMode by remember(source) { mutableStateOf(false) }
    var tab by remember(source) { mutableIntStateOf(0) }
    var edition by remember(source) { mutableStateOf(DEFAULT_EDITION) }
    var editions by remember(source) { mutableStateOf(Load<List<Edition>>(loading = true)) }
    var books by remember(source, edition) { mutableStateOf(Load<List<BibleBook>>(loading = true)) }
    var day by remember(source) { mutableStateOf(LocalDate.now(ZoneId.of("America/Monterrey"))) }
    var form by remember(source) { mutableStateOf("auto") }
    var dayData by remember(source, edition, day, form) { mutableStateOf(Load<DayReadings>(loading = true)) }
    var bookId by remember(source, edition) { mutableStateOf("") }
    var chapter by remember(source, edition) { mutableIntStateOf(1) }
    var verses by remember(source, edition) { mutableStateOf("") }
    var request by remember(source, edition) { mutableStateOf<VerseRequest?>(null) }
    var passageData by remember(source, edition, request) { mutableStateOf(Load<VersePage>()) }
    var query by remember(source) { mutableStateOf("") }
    var mode by remember(source) { mutableStateOf("phrase") }
    var operator by remember(source) { mutableStateOf("AND") }
    var scope by remember(source, edition) { mutableStateOf("all") }
    var searchBook by remember(source, edition) { mutableStateOf("") }
    var searchRequest by remember(source, edition) { mutableStateOf<SearchPageRequest?>(null) }
    var searchData by remember(source, edition, searchRequest) { mutableStateOf(Load<VersePage>()) }
    var compareEdition by remember(source, edition) { mutableStateOf("") }
    var comparison by remember(source, edition, request, compareEdition) { mutableStateOf(Load<VersePage>()) }
    var statistics by remember(source, edition) { mutableStateOf(Load<BibleStats>()) }
    var retry by remember(source) { mutableIntStateOf(0) }

    LaunchedEffect(source, retry) {
        editions = Load(loading = true)
        editions = load { source.translations() }
    }
    LaunchedEffect(source, edition, retry) {
        books = Load(loading = true)
        books = load { source.books(edition) }
    }
    LaunchedEffect(source, edition, day, form, retry) {
        dayData = Load(loading = true)
        dayData = load { source.readings(day, form, edition) }
    }
    LaunchedEffect(source, edition, request, retry) {
        val current = request
        passageData = if (current == null) Load() else {
            passageData = Load(loading = true)
            load { source.verse(current.passage, edition, current.offset).also { require(it.translationId == edition) } }
        }
    }
    LaunchedEffect(source, edition, searchRequest, retry) {
        val current = searchRequest
        searchData = if (current == null) Load() else {
            searchData = Load(loading = true)
            load { source.search(current.query, edition, current.offset).also { require(it.translationId == edition) } }
        }
    }

    LaunchedEffect(edition, request, passageData.value) {
        val current = request
        if (current != null && passageData.value?.items?.isNotEmpty() == true)
            history = library.record(SavedPassage(edition, current.passage))
    }
    LaunchedEffect(source, edition, tab, retry) {
        if (tab == 1) statistics = load { source.analytics(edition) }
    }
    LaunchedEffect(source, request, compareEdition, retry) {
        val current = request
        val other = compareEdition
        if (current != null && other.isNotBlank()) {
            comparison = Load(loading = true)
            comparison = load { source.verse(current.passage, other, current.offset).also { require(it.translationId == other) } }
        }
    }

    fun openPassage(passage: Passage) {
        bookId = passage.bookId
        chapter = passage.chapter
        verses = passage.first?.let { first ->
            if (passage.last != null && passage.last != first) "$first-${passage.last}" else "$first"
        } ?: ""
        request = VerseRequest(passage)
        tab = 1
    }

    ModulePage {
        ModuleHeader("Liturgia", "Lecturas, Biblia y búsqueda")
        ModuleLoading(editions.loading)
        ModuleNotice(if (editions.error) "No se pudieron consultar las traducciones." else null, editions.error)
        val available = editions.value.orEmpty()
        val selected = available.firstOrNull { it.id == edition }
        Choice("Traducción", selected?.name ?: edition, available.map { it.id to it.name }) { edition = it }
        if (selected != null && !mayDisplayText(edition, selected.textAvailable)) {
            ModuleNotice("Esta edición solo tiene referencias disponibles para consulta remota.")
        }
        if (available.isNotEmpty() && selected == null) {
            ModuleNotice("La edición seleccionada no está instalada. Elige otra explícitamente.")
        }
        TabRow(selectedTabIndex = tab) {
            listOf("Hoy", "Biblia", "Buscar").forEachIndexed { i, title ->
                Tab(selected = tab == i, onClick = { tab = i }, text = { Text(title) })
            }
        }
        when (tab) {
            0 -> {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    OutlinedButton(onClick = { day = day.minusDays(1) }) { Text("‹") }
                    TextButton(onClick = { day = LocalDate.now(ZoneId.of("America/Monterrey")) }) { Text(day.toString()) }
                    OutlinedButton(onClick = { day = day.plusDays(1) }) { Text("›") }
                }
                Choice("Formulario", form, listOf("auto" to "Auto", "ordinary" to "Ordinaria", "proper" to "Propia")) { form = it }
                ModuleLoading(dayData.loading)
                ModuleNotice(if (dayData.error) "Lecturas no disponibles." else null, dayData.error)
                dayData.value?.let { result ->
                    Text(result.celebration ?: "Celebración no identificada", style = MaterialTheme.typography.titleLarge)
                    ModuleNotice(result.selectionSource)
                    if (result.status != "available") ModuleNotice("Estado: " + result.status)
                    ModuleNotice("Cobertura: " + result.coverage)
                    result.readings.forEach { reading ->
                        ElevatedCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(reading.label, style = MaterialTheme.typography.titleMedium)
                                Text(reading.citation ?: "Referencia no disponible")
                                ModuleNotice(reading.note)
                                if (mayDisplayText(edition, selected?.textAvailable == true &&
                                        reading.status == "text_available")) reading.verses.forEach { verse ->
                                    verse.text?.let { Text(verse.reference + " · " + it, style = MaterialTheme.typography.bodyLarge) }
                                }
                                reading.ranges.forEach { range ->
                                    TextButton(onClick = { openPassage(range) }) {
                                        Text("Consultar ${range.bookId} ${range.chapter}:${range.first ?: 1}")
                                    }
                                }
                            }
                        }
                    }
                    result.sources.forEach { ModuleNotice(it) }
                }
            }
            1 -> {
                val catalog = books.value.orEmpty()
                val book = catalog.firstOrNull { it.id == bookId }
                ModuleLoading(books.loading)
                ModuleNotice(if (books.error) "Catálogo no disponible." else null, books.error)
                Choice("Libro", book?.name ?: "Seleccionar", catalog.map { it.id to it.name }) {
                    bookId = it
                    chapter = catalog.first { b -> b.id == it }.chapters.firstOrNull() ?: 1
                    request = null
                }
                Choice("Capítulo", chapter.toString(), book?.chapters.orEmpty().map { it.toString() to it.toString() }) {
                    chapter = it.toInt()
                    request = null
                }
                OutlinedTextField(verses, { verses = it; request = null }, label = { Text("Versículos (opcional, 1-10)") },
                    modifier = Modifier.fillMaxWidth(), singleLine = true)
                val range = parseRange(verses)
                Button(enabled = book != null && chapter in book.chapters && (verses.isBlank() || range != null),
                    onClick = { request = VerseRequest(Passage(bookId, chapter, range?.first, range?.last)) }) { Text("Consultar") }
                ModuleActions {
                    val chapters = book?.chapters.orEmpty()
                    val index = chapters.indexOf(chapter)
                    OutlinedButton(enabled = index > 0, onClick = { openPassage(Passage(bookId, chapters[index - 1])) }) { Text("Anterior") }
                    OutlinedButton(enabled = index >= 0 && index < chapters.lastIndex,
                        onClick = { openPassage(Passage(bookId, chapters[index + 1])) }) { Text("Siguiente") }
                }
                statistics.value?.let { Text("${it.books} libros · ${it.chapters} capítulos") }
                request?.let { current ->
                    val saved = SavedPassage(edition, current.passage)
                    ModuleActions {
                        OutlinedButton(onClick = { readingMode = !readingMode }) { Text(if (readingMode) "Tamaño normal" else "Lectura ampliada") }
                        OutlinedButton(onClick = { bookmarks = library.toggle(saved) }) { Text(if (saved in bookmarks) "Quitar marcador" else "Guardar") }
                        OutlinedButton(onClick = {
                            val intent = Intent(Intent.ACTION_SEND).apply {
                                type = "text/plain"
                                putExtra(Intent.EXTRA_TEXT, saved.label)
                            }
                            context.startActivity(Intent.createChooser(intent, "Compartir referencia"))
                        }) { Text("Compartir") }
                    }
                    Choice("Comparar traducción", available.firstOrNull { it.id == compareEdition }?.name ?: "Sin comparación",
                        listOf("" to "Sin comparación") + available.filter { it.id != edition }.map { it.id to it.name }) { compareEdition = it }
                }
                ResultPage(passageData, request?.offset ?: 0, pageSize = 100,
                    onPage = { offset -> request = request?.copy(offset = offset) }, enlarged = readingMode)
                if (compareEdition.isNotBlank() && request != null) {
                    Text("Comparación", style = MaterialTheme.typography.titleMedium)
                    ResultPage(comparison, request?.offset ?: 0, pageSize = 100,
                        onPage = { offset -> request = request?.copy(offset = offset) }, enlarged = readingMode)
                }
                Text("Marcadores", style = MaterialTheme.typography.titleMedium)
                bookmarks.filter { it.edition == edition }.forEach { saved ->
                    TextButton(onClick = { openPassage(saved.passage) }) { Text(saved.label) }
                }
                Text("Historial local", style = MaterialTheme.typography.titleMedium)
                history.filter { it.edition == edition }.forEach { saved ->
                    TextButton(onClick = { openPassage(saved.passage) }) { Text(saved.label) }
                }
                if (history.isNotEmpty()) TextButton(onClick = { history = library.clearHistory() }) { Text("Borrar historial") }
            }
            else -> {
                OutlinedTextField(query, { query = it }, label = { Text("Palabra o frase") },
                    modifier = Modifier.fillMaxWidth(), singleLine = true)
                Choice("Modo", mode, listOf("phrase" to "Frase", "words" to "Palabras", "wildcard" to "Comodín")) { mode = it }
                if (mode == "words") Choice("Operador", operator, listOf("AND" to "Todas", "OR" to "Alguna", "NOT" to "Excluir")) { operator = it }
                Choice("Buscar en", scope, listOf("all" to "Toda la Biblia", "OT" to "Antiguo Testamento",
                    "NT" to "Nuevo Testamento", "DEU" to "Deuterocanónicos", "book" to "Libro")) { scope = it }
                if (scope == "book") Choice("Libro", searchBook.ifBlank { "Seleccionar" },
                    books.value.orEmpty().map { it.id to it.name }) { searchBook = it }
                val search = SearchRequest(query.trim(), mode, operator,
                    testament = scope.takeIf { it in setOf("OT", "NT", "DEU") }, bookId = searchBook.takeIf { scope == "book" && it.isNotBlank() })
                Button(enabled = search.valid() && (scope != "book" || searchBook.isNotBlank()),
                    onClick = { searchRequest = SearchPageRequest(search) }) { Text("Buscar") }
                searchRequest?.let { Text("Resultados: " + it.query.query) }
                ResultPage(searchData, searchRequest?.offset ?: 0, pageSize = 25,
                    onPage = { searchRequest = searchRequest?.copy(offset = it) },
                    onVerse = { openPassage(Passage(it.bookId, it.chapter, it.number, it.number)) })
            }
        }
        OutlinedButton(onClick = { retry++ }) { Text("Actualizar") }
    }
}

internal fun parseRange(value: String): IntRange? {
    val match = Regex("""(\d{1,3})(?:-(\d{1,3}))?""").matchEntire(value.trim()) ?: return null
    val first = match.groupValues[1].toInt()
    val last = match.groupValues[2].ifBlank { match.groupValues[1] }.toInt()
    return if (first in 1..200 && last in first..200) first..last else null
}

@Composable
private fun Choice(label: String, selected: String, items: List<Pair<String, String>>, onSelect: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        Text(label, style = MaterialTheme.typography.labelMedium)
        Box {
            OutlinedButton(onClick = { expanded = true }, enabled = items.isNotEmpty()) { Text(selected) }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                items.forEach { (id, name) ->
                    DropdownMenuItem(text = { Text(name) }, onClick = { expanded = false; onSelect(id) })
                }
            }
        }
    }
}

@Composable
private fun ResultPage(state: Load<VersePage>, offset: Int, pageSize: Int, onPage: (Int) -> Unit, onVerse: ((Verse) -> Unit)? = null, enlarged: Boolean = false) {
    ModuleLoading(state.loading)
    ModuleNotice(if (state.error) "Consulta no disponible." else null, state.error)
    state.value?.let { result ->
        Text("${result.total} versículos · ${result.translationId}")
        if (result.items.isEmpty()) ModuleNotice("Sin resultados en esta edición.")
        val showText = mayDisplayText(result.translationId, result.textAvailable)
        if (!showText) ModuleNotice("Texto no disponible para consulta remota.")
        result.items.forEach { verse ->
            ElevatedCard(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Text(verse.reference, style = MaterialTheme.typography.labelMedium)
                    if (showText) verse.text?.let { Text(it, style = if (enlarged) MaterialTheme.typography.headlineSmall else MaterialTheme.typography.bodyLarge) }
                    if (onVerse != null) TextButton(onClick = { onVerse(verse) }) { Text("Abrir") }
                }
            }
        }
        ModuleActions {
            OutlinedButton(enabled = offset > 0, onClick = { onPage((offset - pageSize).coerceAtLeast(0)) }) { Text("Anterior") }
            OutlinedButton(enabled = result.nextOffset != null, onClick = { result.nextOffset?.let(onPage) }) { Text("Más") }
        }
    }
}
