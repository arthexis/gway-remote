package com.arthexis.gwayremote

/**
 * State transitions for Android's install-permission settings round trip.
 * Android launchers, permission checks, APK verification and installation
 * remain owned by CompanionScreen.
 */
internal data class CompanionInstallPermissionState(val awaitingResult: Boolean = false) {
    fun requested() = copy(awaitingResult = true)
    fun completed() = copy(awaitingResult = false)

    fun result(granted: Boolean): CompanionInstallPermissionResult =
        if (!awaitingResult) CompanionInstallPermissionResult(this, false, null)
        else CompanionInstallPermissionResult(
            completed(),
            granted,
            if (granted) null
            else "Installation permission not granted; allow installs from GWay Remote"
        )

    fun launchFailed(message: String?): CompanionInstallPermissionResult =
        CompanionInstallPermissionResult(
            completed(), false, "Unable to open installation settings: $message"
        )
}

internal data class CompanionInstallPermissionResult(
    val state: CompanionInstallPermissionState,
    val launchInstaller: Boolean,
    val status: String?
)
