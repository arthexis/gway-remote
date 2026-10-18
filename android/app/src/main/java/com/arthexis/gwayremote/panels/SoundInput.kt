package com.arthexis.gwayremote

/** Sound operation contract independent of the Compose controls. */
internal object SoundInput {
    val choices = listOf("ok", "notice", "attention", "warning", "error", "busy", "critical")
    const val defaultSound = "notice"

    fun sound(inputs: Map<String, String>): String =
        inputs["sound"].orEmpty().ifEmpty { defaultSound }

    fun motif(inputs: Map<String, String>): String = inputs["motif"].orEmpty()

    fun valid(inputs: Map<String, String>, availableMotifs: List<String>): Boolean =
        sound(inputs) in choices &&
            (motif(inputs).isEmpty() || motif(inputs) in availableMotifs)

    fun canExecute(
        inputs: Map<String, String>,
        availableMotifs: List<String>,
        loading: Boolean
    ): Boolean = !loading && valid(inputs, availableMotifs)

    fun payload(inputs: Map<String, String>): Map<String, String> =
        mapOf("sound" to sound(inputs), "motif" to motif(inputs))
}
