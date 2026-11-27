package com.arthexis.gwayremote

import com.arthexis.gwayremote.features.deployments.DeploymentConfirmation
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** No deployment call: only the confirmation input is exercised. */
class DeploymentConfirmationTest {
    @get:Rule val rule = createComposeRule()

    @Test fun confirmationStartsUncheckedAndLabelIsClickable() {
        var confirmed by mutableStateOf(false)
        rule.setContent {
            MaterialTheme {
                DeploymentConfirmation("ocpp-csms", confirmed) { confirmed = it }
            }
        }
        rule.runOnIdle { assertFalse(confirmed) }
        rule.onNodeWithTag("rc-deploy-confirm").assertIsOff()
        rule.awaitExportedControl("rc-deploy-confirm") { it.isCheckable && !it.isChecked }
        rule.onNodeWithText("Confirm deployment of ocpp-csms").performClick()
        rule.runOnIdle { assertTrue(confirmed) }
        rule.onNodeWithText("Confirm deployment of ocpp-csms").performClick()
        rule.runOnIdle { assertFalse(confirmed) }
    }
}
