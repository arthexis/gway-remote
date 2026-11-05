package com.arthexis.gwayremote

/**
 * Compile-time metadata for every palette entry. Execution stays in the
 * existing allowlisted operation dispatcher; UI-only features have no command.
 */
enum class FeatureKind { OPERATION, LOCAL_PANEL }

/** Navigation placement only: no change to command or execution authority. */
enum class FeatureGroup { HOME, TOOLS, SETTINGS }

data class FeatureSpec(
    val id: String,
    val label: String,
    val icon: String,
    val keywords: Set<String>,
    val kind: FeatureKind,
    val operation: OperationSpec? = null,
    val group: FeatureGroup = FeatureGroup.TOOLS
) {
    init {
        require(id.matches(Regex("[a-z][a-z0-9-]*")))
        require(label.isNotBlank() && icon.isNotBlank())
        require((kind == FeatureKind.OPERATION) == (operation != null))
        require(operation == null || operation.id == id)
    }

    fun matches(query: String): Boolean {
        val terms = query.trim().lowercase().split(Regex("\\s+")).filter(String::isNotBlank)
        val text = (listOf(id, label) + keywords).joinToString(" ").lowercase()
        return terms.all(text::contains)
    }
}

object FeatureRegistry {
    // MCP Access is a local, inert entry until Watchtower announces gated
    // WebAuthn issuer availability; this does not grant local token authority.
    private val homeOperationIds = setOf("system", "agent-ops")
    private val registered = OperationRegistry.operations.filter { it.visibility == OperationVisibility.PALETTE }.map { operation ->
        FeatureSpec(operation.id, operation.label, operation.icon, operation.keywords,
            FeatureKind.OPERATION, operation,
            if (operation.id in homeOperationIds) FeatureGroup.HOME else FeatureGroup.TOOLS)
    } + listOf(
        FeatureSpec("deployments", "Deployments", "rocket",
            setOf("deploy", "repositories", "follow", "release"), FeatureKind.LOCAL_PANEL, group = FeatureGroup.HOME),
        FeatureSpec("mcp-access", "MCP Access", "key-round",
            setOf("passkey", "webauthn", "bearer", "token", "revoke"), FeatureKind.LOCAL_PANEL,
            group = FeatureGroup.HOME),
        FeatureSpec("github-health", "GitHub Health", "github",
            setOf("github", "ci", "alerts", "watch"), FeatureKind.LOCAL_PANEL, group = FeatureGroup.HOME),
        FeatureSpec("app-update", "App update", "update",
            setOf("apk", "release", "install", "upgrade"), FeatureKind.LOCAL_PANEL, group = FeatureGroup.SETTINGS)
    )

    init {
        require(registered.map { it.id }.distinct().size == registered.size) {
            "Duplicate feature ID"
        }
    }

    val features: List<FeatureSpec> get() = registered

    val home: List<FeatureSpec> get() = registered.filter { it.group == FeatureGroup.HOME }
    val secondary: List<FeatureSpec> get() = registered.filter { it.group != FeatureGroup.HOME }

    /** Searching always includes tucked-away tools; they are not disabled. */
    fun visible(query: String, showSecondary: Boolean): List<FeatureSpec> =
        search(query).filter { query.isNotBlank() || showSecondary || it.group == FeatureGroup.HOME }

    fun get(id: String): FeatureSpec? = registered.firstOrNull { it.id == id }

    fun search(query: String): List<FeatureSpec> = registered.filter { it.matches(query) }
}
