package com.arthexis.gwayremote

internal fun deploymentRevisionLabel(name: String, state: String, staged: String, installed: String): String {
    if (name == "gway-bastion" && state == "staged" &&
        Regex("[0-9a-f]{40}").matches(staged) && (installed.isBlank() || installed == "null")) {
        return "Staged " + staged.take(12) + " · Not activated"
    }
    return "Installed: " + installed.takeIf { it.isNotBlank() && it != "null" }
        ?.take(12).orEmpty().ifBlank { "Unknown" }
}
