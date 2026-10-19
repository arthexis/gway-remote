package com.arthexis.gwayremote

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** A palette action is either an operation or an independent feature. */
data class PaletteAction(
    val id: String,
    val label: String,
    val icon: String,
    val onClick: () -> Unit,
    val enabled: Boolean = true
)

/** Keep visual affordances consistent without adding an icon dependency. */
internal fun paletteIcon(name: String): String = when (name) {
    "heart-pulse" -> "♥"
    "list", "list-check", "list-checks", "list-todo" -> "☷"
    "monitor" -> "▣"
    "plug" -> "⚡"
    "file-text", "clipboard-list", "clipboard-check" -> "▤"
    "activity" -> "◉"
    "search" -> "⌕"
    "play" -> "▶"
    "square" -> "■"
    "gauge" -> "◴"
    "volume-2" -> "♫"
    "github" -> "⌘"
    else -> "•"
}

/**
 * Row capacity is derived from available width. Once a row fills,
 * each button shares the entire row width (including the final row).
 */
@Composable
fun PaletteActionRows(actions: List<PaletteAction>, columns: Int) {
    val count = columns.coerceAtLeast(1)
    actions.chunked(count).forEach { group ->
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            group.forEach { action ->
                OutlinedButton(
                    modifier = Modifier.weight(1f),
                    enabled = action.enabled,
                    onClick = action.onClick
                ) {
                    Text(paletteIcon(action.icon) + " " + action.label, maxLines = 2)
                }
            }
        }
    }
}

@Composable
fun OperationButton(spec: OperationSpec, onOpen: (String) -> Unit, enabled: Boolean = true) {
    OutlinedButton(onClick = { onOpen(spec.id) }, enabled = enabled) {
        Text(paletteIcon(spec.icon) + " " + spec.label)
    }
}
