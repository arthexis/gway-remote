package com.arthexis.gwayremote

/**
 * Compile-time metadata for every palette entry. Execution stays in the
 * existing allowlisted operation dispatcher; UI-only features have no command.
 */
enum class FeatureKind { OPERATION, LOCAL_PANEL }

data class FeatureSpec(
    val id: String,
    val label: String,
    val icon: String,
    val keywords: Set<String>,
    val kind: FeatureKind,
    val operation: OperationSpec? = null
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
    private val registered = OperationRegistry.operations.map { operation ->
        FeatureSpec(operation.id, operation.label, operation.icon, operation.keywords,
            FeatureKind.OPERATION, operation)
    } + listOf(
        FeatureSpec("github-health", "GitHub Health", "github",
            setOf("github", "ci", "alerts", "watch"), FeatureKind.LOCAL_PANEL)
    )

    init {
        require(registered.map { it.id }.distinct().size == registered.size) {
            "Duplicate feature ID"
        }
    }

    val features: List<FeatureSpec> get() = registered

    fun get(id: String): FeatureSpec? = registered.firstOrNull { it.id == id }

    fun search(query: String): List<FeatureSpec> = registered.filter { it.matches(query) }
}
