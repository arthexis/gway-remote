package com.arthexis.gwayremote

import java.net.URI

/**
 * Navigation is a catalogue of destinations, not a catalogue of executable
 * backend commands. In particular, an external destination receives no API
 * bearer, action arguments, or privileges from the Android application.
 */
sealed interface ModuleDestination {
    data class Screen(val id: String) : ModuleDestination

    data class HttpsLink(val url: String) : ModuleDestination {
        init { validateHttpsDestination(url) }
    }

    /** Android App Link bound to one explicitly named installed package. */
    data class AndroidAppLink(val url: String, val packageName: String) : ModuleDestination {
        init {
            validateHttpsDestination(url)
            require(packageName.matches(Regex("[A-Za-z_][A-Za-z0-9_]*(\\.[A-Za-z_][A-Za-z0-9_]*)+"))) {
                "Invalid Android package"
            }
        }
    }
}

private fun validateHttpsDestination(value: String) {
    val uri = runCatching { URI(value) }.getOrNull()
    require(uri != null && uri.scheme.equals("https", ignoreCase = true) &&
        !uri.host.isNullOrBlank() && uri.rawUserInfo == null &&
        uri.rawFragment == null) { "Only explicit HTTPS module links are allowed" }
}

data class AppModule(
    val id: String,
    val label: String,
    val icon: String,
    val destination: ModuleDestination
) {
    init {
        require(id.matches(Regex("[a-z][a-z0-9-]*"))) { "Invalid module ID" }
        require(label.isNotBlank() && icon.isNotBlank())
        if (destination is ModuleDestination.Screen) {
            require(destination.id == id)
            require(id == ModuleRegistry.HOME || id == ModuleRegistry.SETTINGS ||
                FeatureRegistry.get(id) != null) { "Unknown native module" }
        }
    }
}

/**
 * Adding an installed feature requires one declaration in FeatureRegistry.
 * Future externally provided modules can add HttpsLink / AndroidAppLink
 * descriptors here, without changing the shell or expanding API permissions.
 * These are compile-time destinations, never downloaded executable plugins.
 */
object ModuleRegistry {
    const val HOME = "home"
    const val SETTINGS = "settings"

    private val registered = listOf(AppModule(HOME, "Inicio", "home", ModuleDestination.Screen(HOME))) +
        FeatureRegistry.features.filter { it.id != "app-update" }.map { feature ->
            AppModule(feature.id, feature.label, feature.icon, ModuleDestination.Screen(feature.id))
        } + listOfNotNull(
            FeatureRegistry.get("app-update")?.let {
                AppModule(it.id, it.label, it.icon, ModuleDestination.Screen(it.id))
            },
            AppModule(SETTINGS, "Configuración", "settings", ModuleDestination.Screen(SETTINGS))
        )

    init {
        require(registered.map { it.id }.distinct().size == registered.size) { "Duplicate module ID" }
        require(FeatureRegistry.features.all { feature -> registered.any { it.id == feature.id } })
    }

    val modules: List<AppModule> get() = registered
    fun get(id: String): AppModule? = registered.firstOrNull { it.id == id }
}

/** Pure route transition; merely selecting a module never invokes an API command. */
data class ModuleNavigationState(val selectedId: String = ModuleRegistry.HOME) {
    fun select(id: String): ModuleNavigationState {
        val destination = ModuleRegistry.get(id)?.destination
        return if (destination is ModuleDestination.Screen) copy(selectedId = id) else this
    }
}
