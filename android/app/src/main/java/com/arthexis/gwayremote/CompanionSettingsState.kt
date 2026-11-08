package com.arthexis.gwayremote

/**
 * Pure settings state for the companion screen. Persistence and endpoint
 * validation remain with their existing owners; no credentials are logged.
 */
internal data class CompanionSettingsState(
    val endpoint: String,
    val token: String,
    val open: Boolean
) {
    fun toggle(): CompanionSettingsState = copy(open = !open)

    fun saved(): CompanionSettingsState = copy(open = false)

    companion object {
        fun initial(endpoint: String, token: String): CompanionSettingsState =
            CompanionSettingsState(endpoint, token, endpoint.isBlank() || token.isBlank())
    }
}
