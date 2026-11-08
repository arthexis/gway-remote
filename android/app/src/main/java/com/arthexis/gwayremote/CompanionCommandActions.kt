package com.arthexis.gwayremote

import org.json.JSONObject

/**
 * Small action boundary for CompanionScreen. The caller owns coroutine lifecycle,
 * dispatchers, authentication, UI state and cancellation.
 */
internal object CompanionCommandActions {
    suspend fun perform(
        path: String,
        request: suspend () -> JSONObject,
        onCatalog: (List<String>) -> Unit,
        onResult: (String) -> Unit,
        onFailure: (String, Boolean) -> Unit
    ) {
        try {
            val response = request()
            if (path.endsWith("/commands")) {
                onCatalog(ReadOnlyCommandCatalog.names(response.getJSONArray("commands")))
            }
            onResult(response.toString(2))
        } catch (e: Exception) {
            onFailure(e.message ?: "Connection failed", path.endsWith("/commands"))
        }
    }

    suspend fun fetch(
        label: String,
        failures: MutableList<String>,
        request: suspend () -> JSONObject
    ): JSONObject? = try {
        request()
    } catch (e: Exception) {
        failures.add("$label: ${e.message}")
        null
    }
}
