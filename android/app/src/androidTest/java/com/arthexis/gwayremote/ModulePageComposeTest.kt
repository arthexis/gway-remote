package com.arthexis.gwayremote

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.dp
import com.arthexis.gwayremote.ui.components.ModuleActions
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModulePage
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

/** Hermetic Compose checks for the reusable module visual language. */
class ModulePageComposeTest {
    @get:Rule val rule = createComposeRule()

    @Test fun headingsAndErrorsHaveSharedPresentation() {
        rule.setContent {
            MaterialTheme {
                ModulePage {
                    ModuleHeader("CSMS", "Lecturas permitidas")
                    ModuleNotice("Sin conexión", isError = true)
                    ModuleActions {
                        Button(onClick = {}) { Text("Actualizar") }
                    }
                }
            }
        }
        rule.onNodeWithText("CSMS").assertExists()
        rule.onNodeWithText("Lecturas permitidas").assertExists()
        rule.onNodeWithText("Sin conexión").assertExists()
        rule.onNodeWithText("Actualizar").assertExists()
    }

    @Test fun actionsWrapWithoutOverlappingOnNarrowScreens() {
        rule.setContent {
            MaterialTheme {
                Box(Modifier.width(200.dp)) {
                    ModuleActions {
                        Button(onClick = {}) { Text("Primera acción") }
                        Button(onClick = {}) { Text("Segunda acción") }
                    }
                }
            }
        }
        val a = rule.onNodeWithText("Primera acción").getUnclippedBoundsInRoot()
        val b = rule.onNodeWithText("Segunda acción").getUnclippedBoundsInRoot()
        val overlapX = a.left < b.right && b.left < a.right
        val overlapY = a.top < b.bottom && b.top < a.bottom
        assertFalse("Action buttons overlap", overlapX && overlapY)
    }
}
