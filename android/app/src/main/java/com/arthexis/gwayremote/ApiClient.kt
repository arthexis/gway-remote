package com.arthexis.gwayremote

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class ApiClient(private val endpoint: String, private val token: String) {
    init {
        require(endpoint.startsWith("https://") && URL(endpoint).protocol == "https") {
            "A valid HTTPS endpoint is required"
        }
        require(token.isNotBlank()) { "Token is required" }
    }

    fun request(path: String, command: String? = null): JSONObject {
        val base = URL(endpoint.trimEnd('/') + "/")
        require(base.userInfo == null && base.query == null && base.ref == null)
        val target = URL(base, path.removePrefix("/"))
        require(target.host.equals(base.host, ignoreCase = true) && target.protocol == "https")
        val connection = target.openConnection() as HttpURLConnection
        connection.connectTimeout = 5000
        connection.readTimeout = 10000
        connection.instanceFollowRedirects = false
        connection.setRequestProperty("Authorization", "Bearer $token")
        connection.setRequestProperty("Accept", "application/json")
        try {
            if (command != null) {
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                val payload = JSONObject().put("command", command).put("arguments", JSONObject())
                connection.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            if (code !in 200..299) throw ApiException(code)
            val response = connection.inputStream.bufferedReader().use { it.readText() }
            return JSONObject(response)
        } finally {
            connection.disconnect()
        }
    }
}

class ApiException(val status: Int) : Exception(
    when (status) {
        401 -> "Unauthorized: check your token"
        403 -> "Access denied"
        else -> "Server returned HTTP $status"
    }
)
