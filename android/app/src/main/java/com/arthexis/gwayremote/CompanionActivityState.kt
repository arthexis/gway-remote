package com.arthexis.gwayremote

/** UI-only refresh state; networking and panel refresh remain with their owners. */
internal data class CompanionRefreshState(
    val running: Boolean = false,
    val status: String = ""
) {
    fun started() = copy(running = true, status = "Refreshing…")
    fun finished(message: String) = copy(running = false, status = message)
}

/** UI-only update state. No APK, permission, or network behavior lives here. */
internal data class CompanionUpdateState(
    val running: Boolean = false,
    val status: String = ""
) {
    fun started(message: String) = copy(running = true, status = message)
    fun status(message: String) = copy(status = message)
    fun finished() = copy(running = false)
}
