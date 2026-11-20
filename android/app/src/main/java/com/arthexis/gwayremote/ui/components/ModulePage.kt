package com.arthexis.gwayremote.ui.components

import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp

/** One scroll container and one horizontal inset for every native module. */
@Composable
internal fun ModulePage(
    modifier: Modifier = Modifier,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        content = content
    )
}

/** Common first heading under the app-wide top bar; no duplicated app chrome. */
@Composable
internal fun ModuleHeader(title: String, subtitle: String? = null) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        subtitle?.takeIf(String::isNotBlank)?.let {
            Text(it, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
internal fun ModuleSectionTitle(title: String) {
    Text(title, style = MaterialTheme.typography.titleSmall)
}

@Composable
internal fun ModuleLoading(visible: Boolean) {
    if (visible) LinearProgressIndicator(Modifier.fillMaxWidth())
}

/** Identical error/informational typography with polite accessibility updates. */
@Composable
internal fun ModuleNotice(message: String?, isError: Boolean = false) {
    if (message.isNullOrBlank()) return
    Text(
        message,
        style = MaterialTheme.typography.bodySmall,
        color = if (isError) MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }
    )
}

/** Action buttons wrap instead of clipping at narrow phone widths. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ModuleActions(
    content: @Composable FlowRowScope.() -> Unit
) {
    FlowRow(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
        content = content
    )
}
