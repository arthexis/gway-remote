package com.arthexis.gwayremote

import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** One visual shell for operation and local panels; no execution authority. */
@Composable
internal fun PanelChrome(
    id: String,
    title: String,
    position: Int,
    count: Int,
    onMove: (String, Int) -> Unit,
    onClose: (String) -> Unit,
    loading: Boolean = false,
    error: String? = null,
    content: @Composable ColumnScope.() -> Unit
) {
    OutlinedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top) {
                Text(title, style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f).padding(top = 4.dp))
                Row(verticalAlignment = Alignment.Top) {
                    if (position > 0) IconButton(onClick = { onMove(id, position - 1) }) {
                        Icon(Icons.Filled.ArrowUpward, contentDescription = "Move up",
                            modifier = Modifier.size(30.dp))
                    }
                    if (position < count - 1) IconButton(onClick = { onMove(id, position + 1) }) {
                        Icon(Icons.Filled.ArrowDownward, contentDescription = "Move down",
                            modifier = Modifier.size(30.dp))
                    }
                    IconButton(onClick = { onClose(id) }) {
                        Icon(Icons.Filled.Close, contentDescription = "Close panel",
                            modifier = Modifier.size(30.dp))
                    }
                }
            }
            if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
            error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            content()
        }
    }
}
