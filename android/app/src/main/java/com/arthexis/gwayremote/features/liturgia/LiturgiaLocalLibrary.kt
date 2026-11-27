package com.arthexis.gwayremote.features.liturgia

import android.content.Context
import org.json.JSONArray

internal data class SavedPassage(val edition: String, val passage: Passage) {
    fun encode(): String = listOf(edition, passage.bookId, passage.chapter,
        passage.first ?: 0, passage.last ?: 0).joinToString("|")
    val label: String get() = "$edition · ${passage.bookId} ${passage.chapter}" +
        (passage.first?.let { first -> ":$first" + (passage.last?.takeIf { it != first }?.let { "-$it" } ?: "") } ?: "")
    companion object {
        fun decode(raw: String): SavedPassage? = runCatching {
            val (edition, book, chapter, first, last) = raw.split('|').also { require(it.size == 5) }
            require(edition.matches(Regex("[A-Za-z0-9_-]{2,40}")) && book.matches(Regex("[A-Z0-9]{3}")))
            val c = chapter.toInt(); val f = first.toInt(); val l = last.toInt()
            require(c in 1..200 && ((f == 0 && l == 0) || (f in 1..200 && (l == 0 || l in f..200))))
            SavedPassage(edition, Passage(book, c, f.takeIf { it > 0 }, l.takeIf { it > 0 }))
        }.getOrNull()
    }
}

/** Only reference metadata, never text or credentials. Private app storage. */
internal class LiturgiaLocalLibrary(context: Context) {
    private val prefs = context.getSharedPreferences("liturgia_local", Context.MODE_PRIVATE)
    private fun read(key: String): List<SavedPassage> = runCatching {
        val array = JSONArray(prefs.getString(key, "[]") ?: "[]")
        (0 until array.length()).mapNotNull { SavedPassage.decode(array.getString(it)) }.take(30)
    }.getOrDefault(emptyList())
    private fun write(key: String, values: List<SavedPassage>): List<SavedPassage> {
        val bounded = values.distinct().take(30)
        prefs.edit().putString(key, JSONArray(bounded.map { it.encode() }).toString()).apply()
        return bounded
    }
    fun history() = read("history")
    fun bookmarks() = read("bookmarks")
    fun record(value: SavedPassage) = write("history", listOf(value) + history())
    fun toggle(value: SavedPassage): List<SavedPassage> {
        val old = bookmarks()
        return write("bookmarks", if (value in old) old - value else listOf(value) + old)
    }
    fun clearHistory() = write("history", emptyList())
}
