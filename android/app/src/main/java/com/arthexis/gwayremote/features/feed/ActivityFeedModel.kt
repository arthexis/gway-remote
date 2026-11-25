package com.arthexis.gwayremote.features.feed

import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import java.time.Instant

internal const val FEED_ORIGIN = "https://remote.arthexis.com"
internal const val PAGE_SIZE = 20
internal const val CACHE_LIMIT = 100
internal const val CACHE_AGE_MS = 24 * 60 * 60 * 1000L

internal data class FeedItem(
    val seq: Long, val title: String, val summary: String, val category: String,
    val severity: String, val time: String, val received: String,
    val node: String = "", val repository: String = "", val url: String? = null
) {
    fun json() = JSONObject().put("seq", seq).put("title", title).put("summary", summary)
        .put("category", category).put("severity", severity).put("time", time)
        .put("received", received).put("node", node).put("repository", repository)
        .put("url", url ?: JSONObject.NULL)

    val moduleId: String? get() = when (category) {
        "deployment", "deployments" -> "deployments"
        "agentops", "agent-ops" -> "agent-ops"
        "github", "ci" -> "github-health"
        "fleet", "system" -> "system"
        "ocpp", "csms" -> "csms"
        "odoo" -> "odoo-quotations"
        else -> null
    }
}

internal fun safeFeedLink(raw: String?): String? {
    if (raw.isNullOrBlank() || raw.length > 2048 || raw.any { it.isWhitespace() || it == '\\' }) return null
    val uri = runCatching { URI(raw) }.getOrNull() ?: return null
    // Feed text is untrusted; allow only known first-party destinations.
    if (uri.scheme != "https" || uri.host?.lowercase() !in
        setOf("github.com", "remote.arthexis.com", "customer.gelectriic.com") ||
        uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null ||
        uri.port !in setOf(-1, 443)) return null
    if (uri.host.equals("github.com", ignoreCase = true) &&
        !uri.path.startsWith("/arthexis/")) return null
    return raw
}

internal data class FeedPage(val items: List<FeedItem>, val next: Long?, val more: Boolean)

internal fun parseFeedPage(value: JSONObject): FeedPage {
    val array = value.getJSONArray("items")
    require(array.length() <= PAGE_SIZE)
    val items = (0 until array.length()).map { i ->
        val row = array.getJSONObject(i)
        val event = row.getJSONObject("event")
        val data = event.getJSONObject("data")
        val seq = row.getLong("seq")
        require(seq > 0)
        val occurred = event.getString("time")
        val received = row.getString("received_at")
        Instant.parse(occurred)
        Instant.parse(received)
        FeedItem(seq, data.getString("title").take(160), data.getString("summary").take(1024),
            data.getString("category").take(256), data.getString("severity").take(32),
            occurred, received, data.optString("node").take(256),
            data.optString("repository").take(256), safeFeedLink(data.optString("url")))
    }
    require(items.zipWithNext().all { (a,b) -> a.seq > b.seq })
    val next = if (value.isNull("next_cursor")) null else value.getLong("next_cursor")
    val more = value.getBoolean("has_more")
    require(items.isEmpty() || next == items.last().seq)
    require(!more || (items.isNotEmpty() && next != null && next > 0))
    return FeedPage(items, next, more)
}

internal data class FeedState(
    val items: List<FeedItem> = emptyList(),
    val read: Set<Long> = emptySet(),
    val next: Long? = null,
    val more: Boolean = false,
    val savedAt: Long = 0
) {
    fun merge(page: FeedPage, fresh: Boolean, now: Long): FeedState {
        val combined = (if (fresh) page.items else items + page.items)
            .distinctBy { it.seq }.sortedByDescending { it.seq }.take(CACHE_LIMIT)
        // Retain read markers across refresh for bounded recently seen receipts.
        val kept = read.sortedDescending().take(CACHE_LIMIT).toSet()
        return copy(items = combined, read = kept, next = page.next,
            more = page.more && combined.size < CACHE_LIMIT, savedAt = now)
    }

    fun mark(seq: Long): FeedState = if (items.none { it.seq == seq }) this
        else copy(read = (read + seq).sortedDescending().take(CACHE_LIMIT).toSet())

    fun visible(category: String?): List<FeedItem> =
        items.filter { it.seq !in read && (category == null || it.category == category) }

    fun json() = JSONObject().put("items", JSONArray(items.map { it.json() }))
        .put("read", JSONArray(read.toList())).put("next", next ?: JSONObject.NULL)
        .put("more", more).put("saved_at", savedAt)

    companion object {
        fun fromJson(value: JSONObject): FeedState {
            val a = value.getJSONArray("items")
            val r = value.getJSONArray("read")
            require(a.length() <= CACHE_LIMIT && r.length() <= CACHE_LIMIT)
            val items = (0 until a.length()).map { i ->
                val v = a.getJSONObject(i)
                FeedItem(v.getLong("seq"), v.getString("title"), v.getString("summary"),
                    v.getString("category"), v.getString("severity"), v.getString("time"),
                    v.getString("received"), v.optString("node"), v.optString("repository"),
                    safeFeedLink(v.optString("url")))
            }
            require(items.all { it.seq > 0 } && items.zipWithNext().all { (a,b) -> a.seq > b.seq })
            return FeedState(items, (0 until r.length()).map { r.getLong(it) }.toSet(),
                if (value.isNull("next")) null else value.getLong("next"),
                value.getBoolean("more"), value.getLong("saved_at"))
        }
    }
}
