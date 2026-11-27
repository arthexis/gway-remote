package com.arthexis.gwayremote.features.liturgia

import java.time.LocalDate

/** Transport-independent models; no terminal parsing or execution privileges. */
internal const val DEFAULT_EDITION = "spanishdhh"

/** Rights are fail-closed even if an injected or remote source advertises DHH text. */
internal fun mayDisplayText(edition: String, advertised: Boolean): Boolean =
    advertised && !edition.equals(DEFAULT_EDITION, ignoreCase = true)

internal data class Edition(val id: String, val name: String, val textAvailable: Boolean)
internal data class BibleBook(val id: String, val name: String, val testament: String, val chapters: List<Int>)
internal data class Passage(
    val bookId: String, val chapter: Int, val first: Int? = null, val last: Int? = null
)
internal data class Reading(
    val role: String, val label: String, val citation: String?, val status: String,
    val ranges: List<Passage>, val note: String? = null, val verses: List<Verse> = emptyList()
)
internal data class DayReadings(
    val date: LocalDate, val celebration: String?, val selectedForm: String?,
    val coverage: String, val status: String, val readings: List<Reading>,
    val sources: List<String>, val selectionSource: String? = null
)
internal data class Verse(val bookId: String, val chapter: Int, val number: Int, val text: String?) {
    val reference: String get() = "$bookId $chapter:$number"
}
internal data class VersePage(
    val translationId: String, val textAvailable: Boolean, val items: List<Verse>,
    val total: Int, val nextOffset: Int?
)
internal data class SearchRequest(
    val query: String, val mode: String = "phrase", val operator: String = "AND",
    val testament: String? = null, val bookId: String? = null
) {
    fun valid(): Boolean = query.isNotBlank() && query.length <= 160 &&
        mode in setOf("phrase", "words", "wildcard") &&
        operator in setOf("AND", "OR", "NOT") &&
        (testament == null || testament in setOf("OT", "NT", "DEU")) &&
        !(testament != null && bookId != null) &&
        (mode != "wildcard" || (query.length <= 48 &&
            query.count { it == '*' || it == '?' } <= 1))
}

internal data class BibleStats(val books: Int, val chapters: Int)

/** Fixed read-only transport. */
internal interface LiturgiaSource {
    suspend fun analytics(edition: String): BibleStats
    suspend fun translations(): List<Edition>
    suspend fun books(edition: String): List<BibleBook>
    suspend fun readings(day: LocalDate, form: String, edition: String): DayReadings
    suspend fun verse(passage: Passage, edition: String, offset: Int = 0): VersePage
    suspend fun search(request: SearchRequest, edition: String, offset: Int = 0): VersePage
}
