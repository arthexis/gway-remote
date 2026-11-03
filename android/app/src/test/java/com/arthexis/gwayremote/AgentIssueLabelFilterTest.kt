package com.arthexis.gwayremote

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class AgentIssueLabelFilterTest {
    @Test fun refreshedInstanceLabelMovesIssueOutOfUnassigned() {
        val issue = JSONObject("""{"labels":["triage"]}""")
        assertTrue(agentIssueMatchesInstance(issue, "-"))
        assertFalse(agentIssueMatchesInstance(issue, "gway-001"))
        issue.put("labels", org.json.JSONArray("""["triage","gway-001"]"""))
        assertFalse(agentIssueMatchesInstance(issue, "-"))
        assertTrue(agentIssueMatchesInstance(issue, "gway-001"))
        assertFalse(agentIssueMatchesInstance(issue, "gway-002"))
    }

    @Test fun canonicalLabelsSupportStringAndNamedObjectShapes() {
        val issue = JSONObject("""{"labels":["gway-001",{"name":"priority"}]}""")
        assertEquals(setOf("gway-001", "priority"), agentIssueLabels(issue))
        assertTrue(agentIssueMatchesInstance(issue, "gway-001"))
    }

    @Test fun missingLabelsRemainUnassignedAndAllShowsEveryIssue() {
        val issue = JSONObject("""{"labels":[]}""")
        assertTrue(agentIssueMatchesInstance(issue, "-"))
        assertTrue(agentIssueMatchesInstance(issue, "*"))
        assertFalse(agentIssueMatchesInstance(issue, "gway-001"))
    }
}
