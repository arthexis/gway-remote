package com.arthexis.gwayremote

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Owns network jobs and response state; the UI only renders and sends intents. */
internal class DeploymentsViewModel(
    private val repository: DeploymentsRepository = DeploymentsRepository()
) : ViewModel() {
    var overview by mutableStateOf<JSONObject?>(null)
        private set
    var follow by mutableStateOf<JSONObject?>(null)
        private set
    var error by mutableStateOf<String?>(null)
        private set
    var busy by mutableStateOf(false)
        private set
    var requestId by mutableStateOf("")
        private set

    private var overviewJob: Job? = null
    private var followJob: Job? = null
    private var dispatchJob: Job? = null
    private var endpoint = ""
    private var token = ""

    fun connect(endpoint: String, token: String, restoredRequestId: String) {
        val changed = this.endpoint != endpoint || this.token != token
        this.endpoint = endpoint
        this.token = token
        if (changed) {
            overviewJob?.cancel()
            followJob?.cancel()
            overview = null
            follow = null
            refresh()
        }
        if (requestId != restoredRequestId && !busy) observe(restoredRequestId)
    }

    fun refresh() {
        overviewJob?.cancel()
        if (endpoint.isBlank() || token.isBlank()) return
        overviewJob = viewModelScope.launch {
            try {
                overview = repository.overview(endpoint, token).optJSONObject("result")
                error = null
            } catch (e: Exception) {
                error = e.message ?: "Overview unavailable"
            }
        }
        if (requestId.isNotBlank()) observe(requestId, force = true)
    }

    fun observe(id: String, force: Boolean = false) {
        if (requestId == id && !force) return
        followJob?.cancel()
        requestId = id
        follow = null
        if (id.isBlank() || endpoint.isBlank() || token.isBlank()) return
        followJob = viewModelScope.launch {
            while (isActive) {
                try {
                    follow = repository.follow(endpoint, token, id).optJSONObject("result")
                    error = null
                } catch (e: Exception) {
                    error = e.message ?: "Follow unavailable"
                }
                if (follow?.optString("state") == "completed") break
                delay(4000)
            }
        }
    }

    /** A failed HTTP response is ambiguous: never dispatch the same request again. */
    fun dispatch(target: String, id: String, onSubmitted: (String) -> Unit) {
        if (busy || requestId.isNotBlank() || endpoint.isBlank() || token.isBlank()) return
        busy = true
        requestId = id
        onSubmitted(id)
        dispatchJob = viewModelScope.launch {
            try {
                repository.dispatch(endpoint, token, target, id)
                error = null
            } catch (e: Exception) {
                error = e.message ?: "Submission unconfirmed; check Follow"
            } finally {
                busy = false
                observe(id, force = true)
            }
        }
    }

    fun clear(onClear: () -> Unit) {
        if (busy) return
        observe("")
        error = null
        onClear()
    }
}
