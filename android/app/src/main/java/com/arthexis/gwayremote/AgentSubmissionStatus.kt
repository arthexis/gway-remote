package com.arthexis.gwayremote

import org.json.JSONObject

/** Presentation labels follow the actual agent-observe states, not an invented workflow. */
internal enum class AgentSubmissionStatus(val label: String) {
    REQUESTED("Requested"), ACCEPTED("Accepted"), RELEASED("Released"),
    FINISHED("Completed"), CODEX_FAILED("Failed"), INTERRUPTED("Interrupted"),
    REPORTED_UNKNOWN("Report status unknown"), UNKNOWN("Not found");

    companion object {
        fun parse(raw: String?): AgentSubmissionStatus = when (raw) {
            "requested" -> REQUESTED
            "accepted" -> ACCEPTED
            "released" -> RELEASED
            "finished" -> FINISHED
            "codex_failed" -> CODEX_FAILED
            "interrupted" -> INTERRUPTED
            "reported_unknown" -> REPORTED_UNKNOWN
            else -> UNKNOWN
        }
    }

    val terminal: Boolean get() = this in setOf(FINISHED, CODEX_FAILED, INTERRUPTED)
}

/** Display-only gate; authoritative eligibility is rechecked by Agent Ops. */
internal fun agentIssueEligible(issue: JSONObject): Boolean {
    if (!issue.optBoolean("eligible", false)) return false
    val labels = issue.optJSONArray("labels") ?: return false
    return (0 until labels.length()).any { labels.optString(it) == "gway-001" }
}
