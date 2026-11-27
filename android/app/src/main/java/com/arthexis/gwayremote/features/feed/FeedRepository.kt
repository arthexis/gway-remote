package com.arthexis.gwayremote.features.feed

import android.content.Context
import android.util.AtomicFile
import com.arthexis.gwayremote.SecretStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest

internal const val MAX_FEED_RESPONSE = 1024 * 1024
internal fun validFeedToken(token: String) = Regex("gwr_[0-9a-f]{24}_[A-Za-z0-9_-]{1,128}").matches(token)
internal class FeedHttpError(val status: Int) : Exception()

internal fun validMobileFeedKey(token: String) = token.length in 1..153 && token.all { it.code in 33..126 }

internal class FeedRepository(context: Context, endpoint: String = FEED_ORIGIN) {
    private val transport = FeedTransport(context.applicationContext, endpoint)
    suspend fun page(token: String, before: Long? = null): FeedPage = withContext(Dispatchers.IO) {
        require(if (transport.isCanary) validFeedToken(token) else validMobileFeedKey(token))
        require(before == null || before > 0)
        val connection = transport.connection(before)
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
internal class FeedCache(context: Context, private val endpoint: String = FEED_ORIGIN) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "activity-feed.json"))
    private val secrets = SecretStore(context.applicationContext)
    private val transport = FeedTransport(context.applicationContext, endpoint)
    private fun matches(token: String): Boolean = !transport.isCanary && validMobileFeedKey(token) &&
        secrets.token == token && runCatching {
            mobileFeedOrigin(secrets.endpoint.ifBlank { FEED_ORIGIN }) == mobileFeedOrigin(endpoint)
        }.getOrDefault(false)
    // All Home instances and Settings share one file and synchronization boundary.
    private companion object { val lock = Any() }
    private fun fingerprint(token: String): String = MessageDigest.getInstance("SHA-256")
        .digest("mobile-feed-v1\n${transport.cacheIdentity()}\n$token".toByteArray()).joinToString("") { "%02x".format(it.toInt() and 255) }

    fun read(token: String, now: Long = System.currentTimeMillis()): FeedState? = synchronized(lock) {
        runCatching {
            require(matches(token))
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
            require(json.getString("binding") == fingerprint(token))
            val state = FeedState.fromJson(json.getJSONObject("state"))
            require(state.savedAt in (now - CACHE_AGE_MS)..now)
            state
        }.getOrNull()
    }

    fun write(token: String, state: FeedState): Boolean = synchronized(lock) {
        if (!matches(token)) return@synchronized false
        val bytes = JSONObject().put("binding", fingerprint(token)).put("state", state.json())
            .toString().toByteArray(Charsets.UTF_8)
        if (bytes.size > MAX_FEED_RESPONSE) return@synchronized false
        val stream = file.startWrite()
        try { stream.write(bytes); file.finishWrite(stream) }
        catch (e: Exception) { file.failWrite(stream); throw e }
        true
    }

    fun clear(token: String? = null) = synchronized(lock) {
        // A cancelled Home instance cannot delete a newer credential cache.
        if (token == null || matches(token)) file.delete()
    }
}
