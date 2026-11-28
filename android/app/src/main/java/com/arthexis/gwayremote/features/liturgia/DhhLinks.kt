package com.arthexis.gwayremote.features.liturgia

import java.net.URLEncoder

/** Typed references only. Never open a provider-supplied URL or fetch licensed text. */
internal data class DhhPassage(val bookId: String, val chapter: Int, val first: Int?,
    val endChapter: Int = chapter, val last: Int? = first)

private val dhhNames = mapOf(
    "GEN" to "Génesis", "EXO" to "Éxodo", "LEV" to "Levítico", "NUM" to "Números",
    "DEU" to "Deuteronomio", "JOS" to "Josué", "JDG" to "Jueces", "RUT" to "Rut",
    "1SA" to "1 Samuel", "2SA" to "2 Samuel", "1KI" to "1 Reyes", "2KI" to "2 Reyes",
    "1CH" to "1 Crónicas", "2CH" to "2 Crónicas", "EZR" to "Esdras", "NEH" to "Nehemías",
    "EST" to "Ester", "JOB" to "Job", "PSA" to "Salmos", "PRO" to "Proverbios",
    "ECC" to "Eclesiastés", "SNG" to "Cantares", "ISA" to "Isaías", "JER" to "Jeremías",
    "LAM" to "Lamentaciones", "EZK" to "Ezequiel", "DAN" to "Daniel", "HOS" to "Oseas",
    "JOL" to "Joel", "AMO" to "Amós", "OBA" to "Abdías", "JON" to "Jonás",
    "MIC" to "Miqueas", "NAH" to "Nahúm", "HAB" to "Habacuc", "ZEP" to "Sofonías",
    "HAG" to "Hageo", "ZEC" to "Zacarías", "MAL" to "Malaquías", "MAT" to "Mateo",
    "MRK" to "Marcos", "LUK" to "Lucas", "JHN" to "Juan", "ACT" to "Hechos",
    "ROM" to "Romanos", "1CO" to "1 Corintios", "2CO" to "2 Corintios", "GAL" to "Gálatas",
    "EPH" to "Efesios", "PHP" to "Filipenses", "COL" to "Colosenses", "1TH" to "1 Tesalonicenses",
    "2TH" to "2 Tesalonicenses", "1TI" to "1 Timoteo", "2TI" to "2 Timoteo", "TIT" to "Tito",
    "PHM" to "Filemón", "HEB" to "Hebreos", "JAS" to "Santiago", "1PE" to "1 Pedro",
    "2PE" to "2 Pedro", "1JN" to "1 Juan", "2JN" to "2 Juan", "3JN" to "3 Juan",
    "JUD" to "Judas", "REV" to "Apocalipsis",
    "TOB" to "Tobit", "JDT" to "Judit", "WIS" to "Sabiduría", "SIR" to "Eclesiástico",
    "BAR" to "Baruc", "1MA" to "1 Macabeos", "2MA" to "2 Macabeos"
)

// Independent external catalog, not represented as locally installed text.
internal val dhhOnlineBooks = listOf("TOB" to 14, "JDT" to 16, "WIS" to 19, "SIR" to 51,
    "BAR" to 6, "1MA" to 16, "2MA" to 15).map { (id, count) ->
    BibleBook(id, dhhNames.getValue(id), "DEU", (1..count).toList())
}

internal fun Passage.asDhhPassage() = DhhPassage(bookId, chapter, first, chapter, last ?: first)

private fun formatDhh(p: DhhPassage): String? {
    val name = dhhNames[p.bookId] ?: return null
    if (p.chapter !in 1..150 || p.endChapter !in p.chapter..150 ||
        p.endChapter - p.chapter > 3) return null
    val first = p.first
    val last = p.last
    if (first == null && last == null && p.endChapter == p.chapter) return "$name ${p.chapter}"
    if (first == null || last == null || first !in 1..200 || last !in 1..200 ||
        (p.endChapter == p.chapter && last < first)) return null
    val tail = when {
        p.endChapter != p.chapter -> "-${p.endChapter}:$last"
        last != first -> "-$last"
        else -> ""
    }
    return "$name ${p.chapter}:$first$tail"
}

internal fun dhhUrl(passages: List<DhhPassage>): String? {
    if (passages.isEmpty() || passages.size > 40) return null
    val references = passages.map { formatDhh(it) ?: return null }.distinct()
    val query = URLEncoder.encode(references.joinToString(", "), "UTF-8")
    return "https://www.biblegateway.com/passage/?search=$query&version=DHH"
}

internal fun allDailyDhhUrl(day: DayReadings): String? {
    if (day.status in setOf("stale", "calendar_only", "cache_unavailable", "form_unavailable") ||
        day.selectedForm !in setOf("ordinary", "proper")) return null
    if (!day.readings.map { it.role }.containsAll(listOf("first", "psalm", "gospel")) ||
        day.readings.any { it.dhhPassages.isEmpty() }) return null
    return dhhUrl(day.readings.flatMap { it.dhhPassages })
}
