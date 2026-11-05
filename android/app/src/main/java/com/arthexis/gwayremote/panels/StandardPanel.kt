package com.arthexis.gwayremote

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.runtime.Composable

/** Operation policies remain in OperationRegistry, outside the shared shell. */
@Composable
fun StandardPanel(
    spec: OperationSpec,
    panel: OperationPanel,
    position: Int,
    panelCount: Int,
    onMove: (String, Int) -> Unit,
    onClose: (String) -> Unit,
    content: @Composable ColumnScope.() -> Unit
) {
    PanelChrome(panel.id, spec.label, position, panelCount, onMove, onClose,
        loading = panel.loading, error = panel.error, content = content)
}
