package com.arthexis.gwayremote

import android.accessibilityservice.AccessibilityServiceInfo
import android.view.accessibility.AccessibilityNodeInfo
import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.test.platform.app.InstrumentationRegistry

/** Observe the same exported resource-id and state as UiAutomator's XML dump.
 * Raw Compose tag IDs are not fully-qualified Android resource names, so the
 * framework findAccessibilityNodeInfosByViewId lookup is not reliable here.
 */
internal fun ComposeTestRule.awaitExportedControl(
    tag: String,
    predicate: (AccessibilityNodeInfo) -> Boolean
) {
    val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
    val info = automation.serviceInfo
    val priorFlags = info.flags
    try {
        info.flags = priorFlags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
            AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
        automation.serviceInfo = info
        waitUntil(8000) {
            val root = automation.rootInActiveWindow ?: return@waitUntil false
            val queue = java.util.ArrayDeque<AccessibilityNodeInfo>()
            queue.add(root)
            var matches = 0
            var valid = false
            var visited = 0
            while (queue.isNotEmpty() && visited++ < 2048) {
                val node = queue.removeFirst()
                if (node.viewIdResourceName == tag) {
                    matches++
                    valid = predicate(node)
                }
                for (i in 0 until node.childCount) node.getChild(i)?.let(queue::add)
                @Suppress("DEPRECATION")
                node.recycle()
            }
            val complete = queue.isEmpty()
            @Suppress("DEPRECATION")
            while (queue.isNotEmpty()) queue.removeFirst().recycle()
            complete && matches == 1 && valid
        }
    } finally {
        info.flags = priorFlags
        automation.serviceInfo = info
    }
}
