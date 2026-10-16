package com.arthexis.gwayremote

import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable

/**
 * Standard palette entry. Its only responsibility is to request opening the
 * registered operation; the panel manager handles deduplication and execution.
 */
@Composable
fun OperationButton(
    spec: OperationSpec,
    onOpen: (String) -> Unit,
    enabled: Boolean = true
) {
    OutlinedButton(
        onClick = { onOpen(spec.id) },
        enabled = enabled
    ) {
        Text(spec.label)
    }
}
