package com.arthexis.gwayremote

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.material3.MaterialTheme
import com.arthexis.gwayremote.features.odoo.Opportunity
import com.arthexis.gwayremote.features.odoo.OpportunityCopyDialog
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class OdooOpportunityCopyTest {
    @get:Rule val rule = createComposeRule()

    @Test fun copiesExactlyOneValuePerButton() {
        val opportunity = Opportunity(1, "Cliente de prueba", "5550100000",
            "Calle de prueba 10, Ciudad", "Alta", "Nueva", "Modelo de prueba",
            "TESTVIN0000000001", null, null, null)
        val copied = mutableListOf<String>()
        rule.setContent {
            MaterialTheme { OpportunityCopyDialog(opportunity, {}, { copied.add(it) }) }
        }
        opportunity.copyValues.forEachIndexed { index, _ ->
            rule.onNodeWithTag("opportunity-copy-$index").performScrollTo().performClick()
        }
        rule.runOnIdle { assertEquals(opportunity.copyValues, copied) }
    }

    @Test fun missingFieldsCannotBeCopied() {
        val opportunity = Opportunity(1, "Cliente de prueba", "", "", "Alta", "", "",
            "", null, null, null)
        rule.setContent {
            MaterialTheme { OpportunityCopyDialog(opportunity, {}, {}) }
        }
        rule.onNodeWithTag("opportunity-copy-0").assertIsEnabled()
        (1..4).forEach { rule.onNodeWithTag("opportunity-copy-$it").assertIsNotEnabled() }
    }
}
