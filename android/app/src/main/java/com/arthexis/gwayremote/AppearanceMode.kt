package com.arthexis.gwayremote

/** User override of Android night mode. Missing or unknown values follow the system. */
enum class AppearanceMode(val label: String) {
    SYSTEM("System"),
    LIGHT("Light"),
    DARK("Dark");

    fun isDark(systemDark: Boolean): Boolean = when (this) {
        SYSTEM -> systemDark
        LIGHT -> false
        DARK -> true
    }

    companion object {
        fun fromStored(value: String?): AppearanceMode =
            entries.firstOrNull { it.name == value } ?: SYSTEM
    }
}
