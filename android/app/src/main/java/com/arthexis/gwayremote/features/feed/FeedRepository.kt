package com.arthexis.gwayremote.features.feed

import android.content.Context
import android.util.AtomicFile
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.security.MessageDigest

internal const val MAX_FEED_RESPONSE = 1024 * 1024
internal fun validFeedToken(token: String) = Regex("gwr_[0-9a-f]{24}_[A-Za-z0-9_-]{1,128}").matches(token)
internal class FeedHttpError(val status: Int) : Exception()

internal class FeedRepository {
    suspend fun page(token: String, before: Long? = null): FeedPage = withContext(Dispatchers.IO) {
        require(validFeedToken(token))
        require(before == null || before > 0)
        val target = URL("$FEED_ORIGIN/api/feed/events?limit=$PAGE_SIZE" +
            (before?.let { "&before=$it" } ?: ""))
        val connection = target.openConnection(Proxy.NO_PROXY) as HttpURLConnection
        try {
            connection.requestMethod = "GET"
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = 6000
            connection.readTimeout = 6000
            connection.setRequestProperty("Authorization", "Bearer $token")
            connection.setRequestProperty("Accept", "application/json")
            val status = connection.responseCode
            if (status != 200) throw FeedHttpError(status)
            require(connection.contentType.orEmpty().startsWith("application/json"))
            val bytes = connection.inputStream.use { input ->
                val out = ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    require(out.size() + n <= MAX_FEED_RESPONSE)
                    out.write(buffer, 0, n)
                }
                out.toByteArray()
            }
            parseFeedPage(JSONObject(String(bytes, Charsets.UTF_8))).also {
                require(before == null || it.items.all { item -> item.seq < before })
            }
        } finally { connection.disconnect() }
    }
}

/** Private no-backup cache, scoped to exact credential and fixed origin. */
internal class FeedCache(context: Context) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "activity-feed.json"))
    private fun fingerprint(token: String): String = MessageDigest.getInstance("SHA-256")
        .digest("$FEED_ORIGIN\n$token".toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }

    @Synchronized fun read(token: String, now: Long = System.currentTimeMillis()): FeedState? {
        return runCatching {
            val raw = file.openRead().use { input ->
                val out = ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    require(out.size() + n <= MAX_FEED_RESPONSE)
                    out.write(buffer, 0, n)
                }
                out.toByteArray()
            }
            val json = JSONObject(String(raw, Charsets.UTF_8))
            require(validFeedToken(token) && json.getString("binding") == fingerprint(token))
            val state = FeedState.fromJson(json.getJSONObject("state"))
            require(state.savedAt in (now - CACHE_AGE_MS)..now)
            state
        }.getOrNull()
    }

    @Synchronized fun write(token: String, state: FeedState) {
        if (!validFeedToken(token)) return
        val bytes = JSONObject().put("binding", fingerprint(token)).put("state", state.json())
            .toString().toByteArray(Charsets.UTF_8)
        if (bytes.size > MAX_FEED_RESPONSE) return
        val stream = file.startWrite()
        try { stream.write(bytes); file.finishWrite(stream) }
        catch (e: Exception) { file.failWrite(stream); throw e }
    }

    @Synchronized fun clear() = file.delete()
}
