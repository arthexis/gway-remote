package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

data class PaletteAction(
    val id: String,
    val label: String,
    val icon: String,
    val onClick: () -> Unit,
    val enabled: Boolean = true,
    val attention: Boolean = false
)

internal object AppIconRegistry {
    fun get(name: String): ImageVector = when (name) {
        "heart-pulse" -> Icons.Filled.Favorite
        "list", "list-check", "list-checks", "list-todo" -> Icons.Filled.List
        "monitor" -> Icons.Filled.Computer
        "plug" -> Icons.Filled.Bolt
        "file-text", "clipboard-list", "clipboard-check" -> Icons.Filled.Description
        "activity" -> Icons.Filled.ShowChart
        "search" -> Icons.Filled.Search
        "play" -> Icons.Filled.PlayArrow
        "square" -> Icons.Filled.Stop
        "gauge" -> Icons.Filled.Speed
        "volume-2" -> Icons.Filled.VolumeUp
        "github" -> Icons.Filled.Code
        "update" -> Icons.Filled.SystemUpdate
        else -> Icons.Filled.Extension
    }
}

@Composable
fun FeatureButton(action: PaletteAction, modifier: Modifier = Modifier) {
    OutlinedButton(
        modifier = modifier.semantics { contentDescription = action.label },
        enabled = action.enabled,
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp),
        onClick = action.onClick
    ) {
        // A Row measures icon and label as separate siblings. The previous
        // overlaid Box allowed both to paint into the same space, especially
        // with larger font scales and two-line labels.
        Row(
            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Icon(
                imageVector = AppIconRegistry.get(action.icon),
                contentDescription = null,
                modifier = Modifier.size(24.dp)
            )
            Text(
                text = action.label,
                modifier = Modifier.weight(1f),
                textAlign = TextAlign.Center,
                maxLines = 2,
                softWrap = true,
                overflow = TextOverflow.Ellipsis,
                lineHeight = MaterialTheme.typography.labelLarge.lineHeight
            )
            if (action.attention) {
                Icon(
                    imageVector = Icons.Filled.Circle,
                    contentDescription = "Update available",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(12.dp)
                )
            }
        }
    }
}

@Composable
fun PaletteActionRows(actions: List<PaletteAction>, columns: Int) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        actions.chunked(columns.coerceAtLeast(1)).forEach { group ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                group.forEach { action ->
                    Box(Modifier.weight(1f)) {
                        FeatureButton(action, Modifier.fillMaxWidth())
                    }
                }
            }
        }
    }
}

@Composable
fun OperationButton(spec: OperationSpec, onOpen: (String) -> Unit, enabled: Boolean = true) {
    FeatureButton(PaletteAction(spec.id, spec.label, spec.icon, { onOpen(spec.id) }, enabled))
}
