package com.arthexis.gwayremote

/**
 * Update-check action boundary. Caller owns coroutine scope, I/O dispatcher,
 * update storage, permission prompts and APK installation.
 */
internal object CompanionUpdateCheck {
    suspend fun run(
        check: suspend () -> AvailableUpdate?,
        onUpdate: (AvailableUpdate?) -> Unit,
        onStatus: (String) -> Unit,
        onFinished: () -> Unit
    ) {
        try {
            val candidate = check()
            onUpdate(candidate)
            onStatus(if (candidate == null) "App is up to date" else "Update available: ${candidate.version}")
        } catch (e: Exception) {
            onStatus(e.message ?: "Update check failed")
        } finally {
            onFinished()
        }
    }
}
