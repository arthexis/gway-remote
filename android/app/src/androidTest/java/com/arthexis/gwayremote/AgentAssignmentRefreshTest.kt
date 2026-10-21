package com.arthexis.gwayremote

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test

/** Exercise the actual Assignments filters with freshly replaced API rows. */
class AgentAssignmentRefreshTest {
    @get:Rule val rule = createComposeRule()

    private fun issue(labels: List<String>): JSONObject = JSONObject()
        .put("repository", "arthexis/gway-bastion")
        .put("number", 2)
        .put("title", "Validate Bastion")
        .put("url", "https://github.com/arthexis/gway-bastion/issues/2")
        .put("state", "open")
        .put("comments", 0)
        .put("labels", JSONArray(labels))

    @Test fun relabelingMovesIssueBetweenInstanceAndUnassigned() {
        var rows by mutableStateOf(listOf(issue(emptyList())))
        rule.setContent {
            MaterialTheme {
                AgentAssignmentsSection(
                    issues = rows, localAgent = "gway-001", loading = false,
                    error = "", onRefresh = {}, onError = {},
                    expanded = true, onExpandedChange = {}
                )
            }
        }
        rule.onNodeWithText("0 of 1 issues").assertExists()
        rule.onNodeWithText("gway-001").performClick()
        rule.onNodeWithText("Unassigned").performClick()
        rule.onNodeWithText("1 of 1 issues").assertExists()
        rule.runOnIdle { rows = listOf(issue(listOf("gway-001"))) }
        rule.onNodeWithText("0 of 1 issues").assertExists()
        rule.onNodeWithText("Unassigned").performClick()
        rule.onNodeWithText("gway-001").performClick()
        rule.onNodeWithText("1 of 1 issues").assertExists()
    }
}
