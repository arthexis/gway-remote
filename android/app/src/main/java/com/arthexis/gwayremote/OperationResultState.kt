package com.arthexis.gwayremote

/** Reusable response state, independent of navigation and panel placement. */
data class OperationPanel(
    val id: String,
    val inputs: Map<String, String> = emptyMap(),
    val loading: Boolean = false,
    val output: String? = null,
    val error: String? = null,
    val revision: Long = 0L
)
