package com.arthexis.gwayremote

/** LCD command contract, independent of Compose and Android widgets. */
internal object LcdInput {
    fun validLine(value: String): Boolean =
        value.length <= 16 && value.all { it.code in 32..126 }

    fun validDuration(value: String): Boolean =
        value.toIntOrNull()?.let { it in 30..300 } == true

    fun canExecute(inputs: Map<String, String>, loading: Boolean): Boolean {
        val line1 = inputs["line1"].orEmpty()
        val line2 = inputs["line2"].orEmpty()
        val duration = inputs["duration"].orEmpty().ifEmpty { "30" }
        return !loading && (line1.isNotEmpty() || line2.isNotEmpty()) &&
            validLine(line1) && validLine(line2) && validDuration(duration)
    }

    fun payload(inputs: Map<String, String>): Map<String, String> =
        inputs + ("duration" to inputs["duration"].orEmpty().ifEmpty { "30" })
}
