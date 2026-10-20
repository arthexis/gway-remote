package com.arthexis.gwayremote

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

/**
 * Presentation-only adapter for the CSMS CLI output. The authoritative CLI text
 * remains available and no positional column schema is assumed.
 */
internal data class CsmsLine(val label: String, val detail: String, val state: String?) {
    companion object {
        private val stateWords = Regex(
            """\b(Charging|Available|Preparing|SuspendedEVSE|SuspendedEV|Finishing|Faulted|Unavailable|Open|Stopped|Connected|Healthy|Error|Warning)\b""",
            RegexOption.IGNORE_CASE
        )
        fun parse(line: String): CsmsLine {
            val trimmed = line.trim()
            val first = trimmed.split(Regex("""\s{2,}|\s*\|\s*"""), limit = 2)
            val label = first.firstOrNull().orEmpty().ifBlank { trimmed }
            val detail = first.getOrNull(1).orEmpty()
            return CsmsLine(label, detail, stateWords.find(trimmed)?.value)
        }
    }
}

internal fun compactDuration(text: String): String =
    text.replace(Regex("""\b(\d+)\s+days?\s+(\d+)\s+hours?\b"""), "$1d $2h")
        .replace(Regex("""\b(\d+)\s+hours?\s+(\d+)\s+minutes?\b"""), "$1h $2m")
        .replace(Regex("""\b(\d+)\s+minutes?\s+(\d+)\s+seconds?\b"""), "$1m $2s")

@Composable
internal fun CsmsCompactInspection(view: String, output: String) {
    var showRaw by remember(output, view) { mutableStateOf(false) }
    val rows = remember(output) { output.lineSequence().filter { it.isNotBlank() }.map(CsmsLine::parse).toList() }
    if (rows.isEmpty()) {
        Text("No inspection output returned", style = MaterialTheme.typography.bodySmall)
        return
    }
    // Only status/charger-related text is shown as compact rows; other views
    // remain in their original form until dedicated parsers are available.
    if (view in setOf("status", "chargers", "charge-points")) {
        Text("${view.replace('-', ' ').replaceFirstChar { it.uppercase() }}", style = MaterialTheme.typography.titleSmall)
        rows.forEachIndexed { index, row ->
            var expanded by remember(output, index) { mutableStateOf(false) }
            val color = when (row.state?.lowercase()) {
                "charging", "connected", "healthy" -> MaterialTheme.colorScheme.primary
                "faulted", "error" -> MaterialTheme.colorScheme.error
                "preparing", "warning" -> MaterialTheme.colorScheme.tertiary
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            }
            Column(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = 5.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(row.label, modifier = Modifier.weight(1f), maxLines = 1,
                        overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                    row.state?.let { Text(it, color = color, style = MaterialTheme.typography.labelSmall) }
                }
                if (row.detail.isNotBlank()) Text(compactDuration(row.detail), maxLines = if (expanded) Int.MAX_VALUE else 1,
                    overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (expanded) Text(compactDuration(output.lines().filter { it.isNotBlank() }.getOrNull(index).orEmpty()),
                    fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
            }
            HorizontalDivider()
        }
    } else {
        Text(output, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace)
    }
    TextButton(onClick = { showRaw = !showRaw }) { Text(if (showRaw) "Hide raw CSMS output" else "Show raw CSMS output") }
    if (showRaw) Text(output, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
}
