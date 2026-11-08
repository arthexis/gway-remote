package com.arthexis.gwayremote

import org.json.JSONArray

/**
 * Pure adapter for the legacy quick-command list.
 * Only read-only commands with no argument definitions are exposed.
 * Preserve server order and duplicate names, matching the original UI.
 */
internal object ReadOnlyCommandCatalog {
    fun names(entries: JSONArray): List<String> =
        (0 until entries.length()).mapNotNull { index ->
            val item = entries.getJSONObject(index)
            if (item.optBoolean("read_only") &&
                (item.optJSONObject("arguments")?.length() ?: 0) == 0)
                item.optString("name").takeIf { it.isNotBlank() } else null
        }
}
