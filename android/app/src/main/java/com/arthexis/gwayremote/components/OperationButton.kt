package com.arthexis.gwayremote

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/** A palette action is either an operation or an independent feature. */
data class PaletteAction(
    val id: String,
    val label: String,
    val icon: String,
    val onClick: () -> Unit,
    val enabled: Boolean = true
)

/** Keep icon selection centralized; unknown features remain visually usable. */
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
        else -> Icons.Filled.Extension
    }
}

/**
 * Single visual contract for operations and UI-only feature actions.
 * A symmetric trailing inset balances the fixed left icon so text is centered
 * relative to the button, not centered in the remaining space.
 */
@Composable
fun FeatureButton(action: PaletteAction, modifier: Modifier = Modifier) {
    OutlinedButton(
        modifier = modifier.semantics { contentDescription = action.label },
        enabled = action.enabled,
        onClick = action.onClick
    ) {
        Box(Modifier.fillMaxWidth().heightIn(min = 28.dp)) {
            Icon(
                imageVector = AppIconRegistry.get(action.icon),
                contentDescription = null,
                modifier = Modifier.align(Alignment.CenterStart)
            )
            Text(
                text = action.label,
                modifier = Modifier.fillMaxWidth().align(Alignment.Center)
                    .padding(horizontal = 28.dp),
                textAlign = TextAlign.Center,
                maxLines = 2
            )
        }
    }
}

/**
 * Buttons evenly occupy each row, including a partially filled final row.
 * Column selection is controlled by the palette's available-width calculation.
 */
@Composable
fun PaletteActionRows(actions: List<PaletteAction>, columns: Int) {
    val count = columns.coerceAtLeast(1)
    actions.chunked(count).forEach { group ->
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            group.forEach { action ->
                FeatureButton(action = action, modifier = Modifier.weight(1f))
            }
        }
    }
}

@Composable
fun OperationButton(spec: OperationSpec, onOpen: (String) -> Unit, enabled: Boolean = true) {
    FeatureButton(PaletteAction(spec.id, spec.label, spec.icon, { onOpen(spec.id) }, enabled))
}
