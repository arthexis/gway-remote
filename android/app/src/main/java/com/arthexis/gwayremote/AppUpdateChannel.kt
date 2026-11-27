package com.arthexis.gwayremote

/** Stable release APKs belong only to the signed production application.
 * A canary is updated exclusively by the SHA-pinned, manual USB artifact workflow.
 */
internal object AppUpdateChannel {
    const val PRODUCTION_PACKAGE = "com.arthexis.gwayremote"
    const val CANARY_PACKAGE = "$PRODUCTION_PACKAGE.canary"
    const val CANARY_NOTICE = "Las actualizaciones estables están deshabilitadas en la APK canaria"

    fun supportsStableUpdates(packageName: String): Boolean =
        packageName == PRODUCTION_PACKAGE

    fun requireStableUpdates(packageName: String) {
        require(supportsStableUpdates(packageName)) { CANARY_NOTICE }
    }
}
