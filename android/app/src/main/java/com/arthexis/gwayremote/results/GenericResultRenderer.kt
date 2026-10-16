package com.arthexis.gwayremote

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import org.json.JSONArray
import org.json.JSONObject

/**
 * Generic fallback for operation output. Keeps the exact response available and
 * never changes the command contract or the panel's immutable state.
 */
@Composable
fun GenericResultRenderer(output: String) {
    val parsed = remember(output) {
        runCatching { JSONObject(output) as Any }.recoverCatching {
            JSONArray(output) as Any
        }.getOrNull()
    }
    var showRaw by remember(output) { mutableStateOf(false) }
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        when (parsed) {
            is JSONObject -> ResultObject(parsed)
            is JSONArray -> ResultArray(parsed)
            else -> Text(output, style = MaterialTheme.typography.bodySmall)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = { showRaw = !showRaw }) {
                Text(if (showRaw) "Hide JSON" else "View JSON")
            }
            TextButton(onClick = {
                val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                clipboard.setPrimaryClip(ClipData.newPlainText("GWay result", output))
            }) { Text("Copy") }
        }
        if (showRaw) {
            val raw = when (parsed) {
                is JSONObject -> parsed.toString(2)
                is JSONArray -> parsed.toString(2)
                else -> output
            }
            Text(raw, style = MaterialTheme.typography.bodySmall,
                modifier = Modifier.heightIn(max = 320.dp).verticalScroll(rememberScrollState()))
        }
    }
}

@Composable
private fun ResultObject(value: JSONObject, depth: Int = 0) {
    val keys = remember(value) { value.keys().asSequence().toList() }
    if (keys.isEmpty()) {
        Text("Empty object", style = MaterialTheme.typography.bodySmall)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        keys.forEach { key ->
            val item = value.opt(key)
            if (depth < 2 && (item is JSONObject || item is JSONArray)) {
                Text(key, style = MaterialTheme.typography.labelMedium)
                Box(Modifier.padding(start = 12.dp)) { ResultValue(item, depth + 1) }
            } else {
                Text("$key: ${compactValue(item)}", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun ResultArray(value: JSONArray, depth: Int = 0) {
    if (value.length() == 0) {
        Text("Empty list", style = MaterialTheme.typography.bodySmall)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        val shown = minOf(value.length(), 30)
        repeat(shown) { index ->
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("${index + 1}.", style = MaterialTheme.typography.labelSmall)
                ResultValue(value.opt(index), depth)
            }
        }
        if (value.length() > shown) {
            Text("${value.length() - shown} more items; view JSON for all.",
                style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun ResultValue(value: Any?, depth: Int) {
    when {
        depth >= 3 -> Text(compactValue(value), style = MaterialTheme.typography.bodySmall)
        value is JSONObject -> ResultObject(value, depth)
        value is JSONArray -> ResultArray(value, depth + 1)
        else -> Text(compactValue(value), style = MaterialTheme.typography.bodySmall)
    }
}

private fun compactValue(value: Any?): String = when (value) {
    null, JSONObject.NULL -> "null"
    is JSONObject -> "{${value.length()} fields}"
    is JSONArray -> "[${value.length()} items]"
    else -> value.toString()
}
