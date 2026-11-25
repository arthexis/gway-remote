package com.arthexis.gwayremote.ui.shell

import com.arthexis.gwayremote.*
import com.arthexis.gwayremote.ui.components.ModuleHeader
import com.arthexis.gwayremote.ui.components.ModuleSectionTitle
import com.arthexis.gwayremote.ui.components.ModuleLoading
import com.arthexis.gwayremote.ui.components.ModuleNotice
import com.arthexis.gwayremote.ui.components.ModuleActions

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp

/** The drawer is an overlay; its children select destinations, not panels. */
@Composable
internal fun ModuleDrawerContent(
    selectedId: String,
    updateAvailable: Boolean,
    onSelect: (String) -> Unit
) {
    ModalDrawerSheet(Modifier.widthIn(max = 340.dp)) {
        Column(Modifier.fillMaxHeight().verticalScroll(rememberScrollState()).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("GWay Remote", style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp))
            HorizontalDivider()
            ModuleRegistry.modules.forEach { module ->
                val image = when (module.id) {
                    ModuleRegistry.HOME -> Icons.Filled.Home
                    ModuleRegistry.SETTINGS -> Icons.Filled.Settings
                    else -> AppIconRegistry.get(module.icon)
                }
                NavigationDrawerItem(
                    selected = selectedId == module.id,
                    onClick = { onSelect(module.id) },
                    icon = { Icon(image, contentDescription = null) },
                    label = { Text(module.label) },
                    badge = if (updateAvailable && module.id == "app-update") {
                        { Text("●", color = MaterialTheme.colorScheme.primary) }
                    } else null
                )
            }
        }
    }
}

/** Home is about the Android app; backend diagnostics have their own module. */
@Composable
internal fun ModuleHomePage(
    installedVersion: String,
    configuredEndpoint: String,
    availableUpdate: AvailableUpdate?,
    updateStatus: String,
    updating: Boolean,
    onOpenUpdate: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        ModuleHeader("Aplicación")
        ElevatedCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("GWay Remote", style = MaterialTheme.typography.titleLarge)
                Text("Versión instalada: " + installedVersion)
                Text("API: " + configuredEndpoint)
                availableUpdate?.let { Text("Actualización disponible: " + it.version) }
                ModuleLoading(updating)
                ModuleNotice(updateStatus, isError = updateStatus.startsWith("Update check failed"))
                ModuleActions {
                    Button(onClick = onOpenUpdate) { Text("Actualizaciones") }
                }
            }
        }
    }
}

@Composable
internal fun ModuleUpdatePage(
    update: AvailableUpdate?,
    updateStatus: String,
    updating: Boolean,
    apkReady: Boolean,
    onCheck: () -> Unit,
    onDownload: () -> Unit,
    onInstall: () -> Unit
) {
    LaunchedEffect(Unit) { onCheck() }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ModuleHeader("Actualizaciones de la aplicación")
        ModuleLoading(updating)
        Text(if (update == null) "No hay una actualización disponible detectada."
            else "Nueva versión: " + update.version)
        ModuleNotice(updateStatus, isError = updateStatus.startsWith("Update check failed"))
        if (update != null) {
            Button(onClick = onDownload, enabled = !updating) {
                Text("Descargar y verificar APK")
            }
            if (apkReady) {
                OutlinedButton(onClick = onInstall, enabled = !updating) {
                    Text("Instalar APK verificado")
                }
            }
        }
    }
}

@Composable
internal fun ModuleSettingsPage(
    settings: CompanionSettingsState,
    appearance: AppearanceMode,
    onAppearanceChange: (AppearanceMode) -> Unit,
    onEndpointChange: (String) -> Unit,
    onTokenChange: (String) -> Unit,
    onSave: () -> Unit,
    feedback: String
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        ModuleSectionTitle("Apariencia")
        ModuleActions {
            AppearanceMode.entries.forEach { mode ->
                FilterChip(
                    selected = appearance == mode,
                    onClick = { onAppearanceChange(mode) },
                    label = { Text(mode.label) }
                )
            }
        }
        HorizontalDivider()
        ModuleSectionTitle("API")
        OutlinedTextField(settings.endpoint, onEndpointChange, label = { Text("HTTPS endpoint") },
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(settings.token, onTokenChange, label = { Text("Bearer token") },
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(onClick = onSave) { Text("Guardar configuración") }
        ModuleNotice(feedback, isError = feedback != "Configuración guardada")
    }
}
