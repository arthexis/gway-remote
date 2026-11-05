package com.arthexis.gwayremote

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Network boundary: no Compose state or UI dependencies. */
internal class DeploymentsRepository {
    suspend fun overview(endpoint: String, token: String): JSONObject =
        withContext(Dispatchers.IO) {
            ApiClient(endpoint.trim(), token).request("/api/v1/execute", "deployments-overview")
        }

    suspend fun follow(endpoint: String, token: String, requestId: String): JSONObject =
        withContext(Dispatchers.IO) {
            ApiClient(endpoint.trim(), token).request("/api/v1/execute", "deployments-follow",
                JSONObject().put("request_id", requestId))
        }

    suspend fun dispatch(endpoint: String, token: String, target: String, requestId: String) {
        withContext(Dispatchers.IO) {
            ApiClient(endpoint.trim(), token).request("/api/v1/execute", "deployments-dispatch",
                JSONObject().put("target", target).put("request_id", requestId).put("confirm", true))
        }
    }
}
