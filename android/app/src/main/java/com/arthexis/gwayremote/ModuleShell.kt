package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
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
    onOpenUpdate: () -> Unit,
    onCheckUpdate: () -> Unit,
    onOpenSettings: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
        Text("Aplicación", style = MaterialTheme.typography.headlineSmall)
        ElevatedCard(Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("GWay Remote", style = MaterialTheme.typography.titleLarge)
                Text("Versión instalada: " + installedVersion)
                Text("API: " + configuredEndpoint)
                Text(if (availableUpdate == null) "Sin actualización pendiente detectada"
                    else "Actualización disponible: " + availableUpdate.version)
                if (updating) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (updateStatus.isNotBlank()) Text(updateStatus, style = MaterialTheme.typography.bodySmall)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onOpenUpdate) { Text("Actualizaciones") }
                    OutlinedButton(onClick = onCheckUpdate, enabled = !updating) {
                        Text("Comprobar")
                    }
                }
            }
        }
        OutlinedButton(onClick = onOpenSettings) { Text("Configuración") }
        Text("Abre el menú ☰ para seleccionar un módulo. Cada módulo tiene su propia pantalla.",
            style = MaterialTheme.typography.bodyMedium)
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
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Actualizaciones de la aplicación", style = MaterialTheme.typography.titleLarge)
        if (updating) LinearProgressIndicator(Modifier.fillMaxWidth())
        Text(if (update == null) "No hay una actualización disponible detectada."
            else "Nueva versión: " + update.version)
        if (updateStatus.isNotBlank()) Text(updateStatus, style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = onCheck, enabled = !updating) { Text("Comprobar actualizaciones") }
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
        Text("Apariencia", style = MaterialTheme.typography.titleMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AppearanceMode.entries.forEach { mode ->
                FilterChip(
                    selected = appearance == mode,
                    onClick = { onAppearanceChange(mode) },
                    label = { Text(mode.label) }
                )
            }
        }
        HorizontalDivider()
        Text("API", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(settings.endpoint, onEndpointChange, label = { Text("HTTPS endpoint") },
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        OutlinedTextField(settings.token, onTokenChange, label = { Text("Bearer token") },
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(), singleLine = true)
        Button(onClick = onSave) { Text("Guardar configuración") }
        if (feedback.isNotBlank()) Text(feedback, style = MaterialTheme.typography.bodySmall)
    }
}
