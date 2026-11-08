package com.arthexis.gwayremote

import org.json.JSONObject

/** Pure state for the sound motif catalog; networking stays in CompanionScreen. */
internal data class CompanionSoundMotifsState(val available: List<String> = emptyList()) {
    fun loaded(response: JSONObject): CompanionSoundMotifsState {
        val array = response.optJSONObject("result")?.optJSONArray("motifs")
        return copy(available = if (array == null) emptyList()
            else (0 until array.length()).map { array.getString(it) })
    }

    fun failed() = copy(available = emptyList())
}
