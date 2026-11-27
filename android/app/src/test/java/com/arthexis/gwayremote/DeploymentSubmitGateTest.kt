package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.deployments.canRequestDeployment
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** UI prerequisites mirror the independent ViewModel dispatch guard. */
class DeploymentSubmitGateTest {
    private val endpoint = "https://remote.arthexis.com"
    private val token = "test-only-token"

    @Test fun credentialAndConfirmationGateFailClosed() {
        assertFalse(canRequestDeployment(false, endpoint, token, false, ""))
        assertFalse(canRequestDeployment(true, endpoint, "", false, ""))
        assertFalse(canRequestDeployment(true, endpoint, "  ", false, ""))
        assertFalse(canRequestDeployment(true, "", token, false, ""))
        assertFalse(canRequestDeployment(true, "  ", token, false, ""))
        assertFalse(canRequestDeployment(true, endpoint, token, true, ""))
        assertFalse(canRequestDeployment(true, endpoint, token, false, "pending-request"))
        assertTrue(canRequestDeployment(true, endpoint, token, false, ""))
    }
}
