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
import org.junit.Assert.assertEquals
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.arthexis.gwayremote.ui.shell.ModuleUpdatePage
import com.arthexis.gwayremote.features.deployments.DeploymentSubmitButton
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
    @Test fun deploymentIsDisabledWithoutTokenEvenAfterExplicitConfirmation() {
        var token by mutableStateOf("")
        var confirmed by mutableStateOf(true)
        var dispatched = 0
        rule.setContent {
            MaterialTheme {
                DeploymentSubmitButton(
                    selected = "all", confirmed = confirmed,
                    endpoint = "https://remote.arthexis.com", token = token,
                    busy = false, requestId = ""
                ) { dispatched++ }
            }
        }
        rule.onNodeWithText("Deploy all").assertIsNotEnabled()
        rule.runOnIdle { assertEquals(0, dispatched); token = "test-only-token" }
        rule.onNodeWithText("Deploy all").assertIsEnabled()
        rule.onNodeWithText("Deploy all").performClick()
        rule.runOnIdle { assertEquals(1, dispatched); confirmed = false }
        rule.onNodeWithText("Deploy all").assertIsNotEnabled()
    }

    @Test fun canaryUpdatePageCannotDownloadOrInstallStableRelease() {
        var requests = 0
        rule.setContent {
            MaterialTheme {
                ModuleUpdatePage(
                    update = AvailableUpdate("9.9.9", 999L, "https://example.test/app.apk", "test", 1),
                    updateStatus = AppUpdateChannel.CANARY_NOTICE,
                    updating = false, apkReady = true,
                    onCheck = { requests++ }, onDownload = { requests++ },
                    onInstall = { requests++ },
                    updatesEnabled = false
                )
            }
        }
        rule.onNodeWithText(AppUpdateChannel.CANARY_NOTICE).assertExists()
        rule.onNodeWithText("Comprobar actualizaciones").assertDoesNotExist()
        rule.onNodeWithText("Descargar y verificar APK").assertDoesNotExist()
        rule.onNodeWithText("Instalar APK verificado").assertDoesNotExist()
        rule.runOnIdle { assertEquals(0, requests) }
    }

}
