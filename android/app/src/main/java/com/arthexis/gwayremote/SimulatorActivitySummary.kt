package com.arthexis.gwayremote

/** Best-effort display hints from captured logs, not a protocol audit. */
data class SimulatorMilestone(val label: String, val evidence: String)

object SimulatorActivitySummary {
    private val actions = listOf(
        "BootNotification", "Authorize", "StartTransaction",
        "MeterValues", "StopTransaction"
    )
    private val replyWords = Regex("\\b(accepted|rejected|invalid|blocked|expired|concurrenttx)\\b",
        RegexOption.IGNORE_CASE)
    private val receivedWords = Regex("\\b(received|response|reply|result|confirmation|conf)\\b",
        RegexOption.IGNORE_CASE)
    private val sentWords = Regex("\\b(sent|sending|request|call)\\b",
        RegexOption.IGNORE_CASE)

    fun parse(output: String, truncated: Boolean): List<SimulatorMilestone> {
        val lines = output.lineSequence().takeLastBounded(1500)
        val milestones = mutableListOf<SimulatorMilestone>()
        for (line in lines) {
            val action = actions.firstOrNull { line.contains(it, ignoreCase = true) }
                ?: continue
            val received = receivedWords.containsMatchIn(line)
            val reply = replyWords.find(line)?.value?.lowercase()
            val evidence = when {
                received && reply != null -> "Response: $reply"
                received -> "Response observed (outcome unknown)"
                sentWords.containsMatchIn(line) -> "Request observed (not confirmed)"
                else -> "Mentioned in output (outcome unknown)"
            }
            val milestone = SimulatorMilestone(action, evidence)
            if (milestones.lastOrNull() != milestone) milestones.add(milestone)
        }
        if (truncated) milestones.add(0,
            SimulatorMilestone("Partial log", "Earlier activity may be missing"))
        return milestones.takeLast(80)
    }

    private fun Sequence<String>.takeLastBounded(max: Int): List<String> {
        val queue = ArrayDeque<String>()
        for (line in this) {
            if (queue.size == max) queue.removeFirst()
            queue.addLast(line)
        }
        return queue.toList()
    }
}
