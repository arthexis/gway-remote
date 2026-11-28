package com.arthexis.gwayremote.features.liturgia

import com.arthexis.gwayremote.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import org.json.JSONArray
import java.time.LocalDate

internal class AuthenticatedLiturgiaSource(private val endpoint: String, private val token: String) : LiturgiaSource {
    private suspend fun read(tool: String, args: JSONObject = JSONObject()): JSONObject =
        withContext(Dispatchers.IO) {
            val response = ApiClient(endpoint.trim(), token).request("/api/v1/execute", "liturgia-read",
                JSONObject().put("tool", tool).put("arguments", args), timeoutMs = 20000)
            require(response.getString("command") == "liturgia-read" && response.getString("status") == "completed")
            response.getJSONObject("result").also { require(it.getInt("schema_version") == 1) }
        }

    override suspend fun analytics(edition: String): BibleStats {
        val data = read("analytics", JSONObject().put("translation", edition))
        require(data.getString("translation_id") == edition)
        return BibleStats(data.getInt("books"), data.getInt("chapters"))
    }

    override suspend fun translations(): List<Edition> =
        read("translations").getJSONArray("items").objects().map {
            Edition(it.getString("id"), it.getString("name"), mayDisplayText(it.getString("id"), it.getBoolean("text_available")))
        }

    override suspend fun books(edition: String): List<BibleBook> =
        read("books", JSONObject().put("translation", edition)).also {
            require(it.getString("translation_id") == edition)
        }.getJSONArray("items").objects().map {
            val chapters = it.getJSONArray("chapters")
            BibleBook(it.getString("id"), it.getString("name"), it.getString("testament"),
                (0 until chapters.length()).map { i -> chapters.getInt(i) })
        }

    override suspend fun readings(day: LocalDate, form: String, edition: String): DayReadings {
        val data = read("readings", JSONObject().put("day", day.toString()).put("form", form).put("translation", edition))
        require(data.getString("date") == day.toString() && data.getString("translation_id") == edition)
        return DayReadings(day, data.optionalString("celebration"), data.optionalString("selected_form"),
            data.getString("coverage"), data.getString("status"),
            data.getJSONArray("readings").objects().map {
                Reading(it.getString("role"), it.getString("label"), it.optionalString("citation"), it.getString("status"),
                    it.getJSONArray("ranges").objects().map { r ->
                        Passage(r.getString("book_id"), r.getInt("chapter"), r.getInt("first"), r.getInt("last"))
                    }, it.optionalString("note"),
                    if (mayDisplayText(edition, it.getString("status") == "text_available"))
                        it.getJSONArray("verses").objects().map { v ->
                            Verse(v.getString("book_id"), v.getInt("chapter"), v.getInt("verse"), v.optionalString("text"))
                        } else emptyList(),
                    it.optJSONArray("dhh_passages")?.objects()?.map { r ->
                        DhhPassage(r.getString("book_id"), r.getInt("chapter"), r.getInt("first"),
                            r.getInt("end_chapter"), r.getInt("last"))
                    }.orEmpty(), it.optionalString("dhh_note"))
            }, data.getJSONArray("sources").objects().map {
                listOfNotNull(it.optionalString("name"), it.optionalString("url")).joinToString(" · ")
            }, data.optionalString("selection_source"))
    }

    override suspend fun verse(passage: Passage, edition: String, offset: Int): VersePage =
        decodePage(read("verse", JSONObject().put("translation", edition).put("book_id", passage.bookId)
            .put("chapter", passage.chapter).put("offset", offset).put("limit", 100).apply {
                passage.first?.let { put("first", it) }
                passage.last?.let { put("last", it) }
            }), edition)

    override suspend fun search(request: SearchRequest, edition: String, offset: Int): VersePage =
        decodePage(read("search", JSONObject().put("translation", edition).put("query", request.query)
            .put("mode", request.mode).put("operator", request.operator).put("offset", offset).put("limit", 25).apply {
                request.testament?.let { put("testament", it) }
                request.bookId?.let { put("book_id", it) }
            }), edition)

    private fun decodePage(data: JSONObject, edition: String): VersePage {
        require(data.getString("translation_id") == edition)
        val allowed = mayDisplayText(edition, data.getBoolean("text_available"))
        return VersePage(edition, allowed, data.getJSONArray("items").objects().map {
            Verse(it.getString("book_id"), it.getInt("chapter"), it.getInt("verse"),
                if (allowed) it.optionalString("text") else null)
        }, data.getInt("total"), if (data.isNull("next_offset")) null else data.getInt("next_offset"))
    }
}
private fun JSONObject.optionalString(key: String): String? = if (isNull(key)) null else getString(key)
private fun JSONArray.objects(): List<JSONObject> = (0 until length()).map { getJSONObject(it) }
