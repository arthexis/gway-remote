package com.arthexis.gwayremote

import org.junit.Assert.assertEquals
import org.junit.Test

class DeploymentRevisionLabelTest {
    @Test fun stagedBastionDoesNotClaimInstalled() {
        val sha = "a".repeat(40)
        assertEquals("Staged " + sha.take(12) + " · Not activated",
            deploymentRevisionLabel("gway-bastion", "staged", sha, "null"))
    }

    @Test fun unknownIsNotStaged() {
        assertEquals("Installed: Unknown",
            deploymentRevisionLabel("gway-bastion", "unknown", "a".repeat(40), "null"))
    }
}
