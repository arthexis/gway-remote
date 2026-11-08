package com.arthexis.gwayremote

/**
 * UI-neutral transfer sequencing. Caller owns the Android installer,
 * permission checks, verified APK storage and coroutine scope.
 */
internal object CompanionUpdateTransfer {
    suspend fun <T> download(
        transfer: suspend () -> T,
        onDownloaded: (T) -> Unit,
        onStatus: (String) -> Unit,
        onFinished: () -> Unit,
        requestInstall: () -> Unit
    ) {
        var downloaded = false
        try {
            onDownloaded(transfer())
            onStatus("Download verified; ready to install")
            downloaded = true
        } catch (e: Exception) {
            onStatus(e.message ?: "Update failed")
        } finally {
            onFinished()
        }
        if (downloaded) requestInstall()
    }

    suspend fun install(
        verify: suspend () -> Unit,
        launch: () -> Unit,
        onStatus: (String) -> Unit,
        onFinished: () -> Unit
    ) {
        try {
            verify()
            launch()
            onStatus("Android installer requested. Confirm the update in the system dialog.")
        } catch (e: Exception) {
            onStatus("Installation could not start: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            onFinished()
        }
    }
}
