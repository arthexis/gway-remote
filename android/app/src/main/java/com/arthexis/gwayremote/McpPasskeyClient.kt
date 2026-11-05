package com.arthexis.gwayremote

import android.util.Base64
import androidx.activity.ComponentActivity
import androidx.credentials.CreatePublicKeyCredentialRequest
import androidx.credentials.CreatePublicKeyCredentialResponse
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetPublicKeyCredentialOption
import androidx.credentials.PublicKeyCredential
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.UUID

/** Administrative passkey transport. No bearer, credentials or result is persisted. */
internal object McpPasskeyClient {
    const val RP_ORIGIN = "https://remote.arthexis.com"
    const val RP_ID = "remote.arthexis.com"
    private const val ROOT = "$RP_ORIGIN/admin/v1"
    private const val LIMIT = 16384

    fun issueIntent(): JSONObject = JSONObject()
        .put("action", "issue_mcp_bearer")
        .put("scopes", JSONArray().put("gway:execute").put("gway:read"))
        .put("lifetime_seconds", 86400)
        .put("request_id", UUID.randomUUID().toString().replace("-", ""))

    fun revokeIntent(id: String): JSONObject {
        require(Regex("[0-9a-f]{24}").matches(id)) { "Invalid bearer ID" }
        return JSONObject().put("action", "revoke_mcp_bearer")
            .put("key_id", id).put("request_id", UUID.randomUUID().toString().replace("-", ""))
    }

    fun validPrincipal(value: String): Boolean =
        Regex("[A-Za-z0-9_-]{1,128}").matches(value)

    private fun path(route: String): String {
        require(route in setOf(
            "enrollment/begin", "enrollment/complete", "bearer/combined/options",
            "bearer/combined/finish", "bearer/revoke/options", "bearer/revoke/finish",
            "capabilities"
        ))
        return "$ROOT/$route"
    }

    private fun call(route: String, body: JSONObject? = null): JSONObject {
        val connection = URL(path(route)).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = if (body == null) "GET" else "POST"
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 8000
            connection.readTimeout = 12000
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            if (body != null) {
                val encoded = body.toString().toByteArray(StandardCharsets.UTF_8)
                require(encoded.size in 1..LIMIT)
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(encoded) }
            }
            if (connection.responseCode != 200 ||
                !connection.contentType.orEmpty().startsWith("application/json")) {
                // Never propagate server body: it may contain grant/token diagnostics.
                throw IllegalStateException("Watchtower administrative access unavailable")
            }
            val payload = connection.inputStream.use { stream ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(2048)
                while (true) {
                    val n = stream.read(buffer)
                    if (n < 0) break
                    output.write(buffer, 0, n)
                    require(output.size() <= LIMIT) { "Oversized response" }
                }
                JSONObject(String(output.toByteArray(), StandardCharsets.UTF_8))
            }
            return payload
        } finally {
            connection.disconnect()
        }
    }

    suspend fun available(): Boolean = withContext(Dispatchers.IO) {
        runCatching {
            val info = call("capabilities")
            info.optBoolean("passkeys_enabled", false) &&
                info.optString("rp_id") == RP_ID
        }.getOrDefault(false)
    }

    private fun b64(value: ByteArray): String =
        Base64.encodeToString(value, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)

    private fun creationOptions(principal: String, challenge: JSONObject): String {
        require(challenge.getString("rp_id") == RP_ID)
        require(challenge.getString("origin") == RP_ORIGIN)
        return JSONObject()
            .put("challenge", challenge.getString("challenge"))
            .put("rp", JSONObject().put("id", RP_ID).put("name", "GWay Remote Watchtower"))
            .put("user", JSONObject().put("id", b64(principal.toByteArray(StandardCharsets.UTF_8)))
                .put("name", principal).put("displayName", principal))
            .put("pubKeyCredParams", JSONArray().put(
                JSONObject().put("type", "public-key").put("alg", -7)))
            .put("timeout", 120000)
            .put("authenticatorSelection", JSONObject()
                .put("residentKey", "required").put("userVerification", "required"))
            .put("attestation", "none").toString()
    }

    private fun assertionOptions(challenge: JSONObject): String {
        require(challenge.getString("rp_id") == RP_ID)
        require(challenge.getString("origin") == RP_ORIGIN)
        return JSONObject().put("challenge", challenge.getString("challenge"))
            .put("rpId", RP_ID).put("timeout", 120000)
            .put("userVerification", "required").toString()
    }

    suspend fun enroll(activity: ComponentActivity, principal: String, grant: String) {
        require(validPrincipal(principal))
        require(grant.length in 32..128)
        val start = withContext(Dispatchers.IO) {
            call("enrollment/begin", JSONObject().put("principal", principal).put("grant", grant))
        }
        val request = CreatePublicKeyCredentialRequest(creationOptions(principal, start))
        val response = CredentialManager.create(activity).createCredential(activity, request)
                as? CreatePublicKeyCredentialResponse
            ?: throw IllegalStateException("Passkey registration unavailable")
        withContext(Dispatchers.IO) {
            val finish = JSONObject().put("principal", principal)
                .put("challenge", start.getString("challenge"))
                .put("ticket", start.getString("ticket"))
                .put("credential", JSONObject(response.registrationResponseJson))
            require(call("enrollment/complete", finish).optBoolean("registered")) {
                "Passkey registration not accepted"
            }
        }
    }

    private suspend fun signedAction(
        activity: ComponentActivity, principal: String,
        route: String, intent: JSONObject
    ): JSONObject {
        require(validPrincipal(principal))
        val start = withContext(Dispatchers.IO) {
            call("$route/options", JSONObject().put("principal", principal).put("intent", intent))
        }
        val request = GetCredentialRequest(listOf(GetPublicKeyCredentialOption(assertionOptions(start))))
        val result = CredentialManager.create(activity).getCredential(activity, request).credential
                as? PublicKeyCredential
            ?: throw IllegalStateException("Passkey authentication unavailable")
        return withContext(Dispatchers.IO) {
            call("$route/finish", JSONObject().put("principal", principal)
                .put("intent", intent).put("challenge", start.getString("challenge"))
                .put("credential", JSONObject(result.authenticationResponseJson)))
        }
    }

    suspend fun issue(activity: ComponentActivity, principal: String): Pair<String, String> {
        val response = signedAction(activity, principal, "bearer/combined", issueIntent())
        val token = response.getString("bearer")
        val id = response.getString("bearer_id")
        require(Regex("gwr_[0-9a-f]{24}_[A-Za-z0-9_-]+").matches(token))
        require(token.split("_")[1] == id)
        return id to token
    }

    suspend fun revoke(activity: ComponentActivity, principal: String, keyId: String): Boolean =
        signedAction(activity, principal, "bearer/revoke", revokeIntent(keyId))
            .getBoolean("revoked")
}
