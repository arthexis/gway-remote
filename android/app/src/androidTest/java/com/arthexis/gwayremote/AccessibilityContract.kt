package com.arthexis.gwayremote

import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.compose.ui.test.onNodeWithTag
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue

/** Check the actual Android accessibility provider's exported node rather than
 * relying on the instrumented activity becoming the OS active window.
 * Physical acceptance independently inspects UiAutomator's USB hierarchy.
 */
internal fun ComposeTestRule.awaitExportedControl(
    tag: String,
    predicate: (AccessibilityNodeInfo) -> Boolean
) {
    val semantic = onNodeWithTag(tag, useUnmergedTree = true).fetchSemanticsNode()
    val root = requireNotNull(semantic.root)
    runOnIdle {
        val view = root as View
        root.forceAccessibilityForTesting(true)
        try {
            val provider = requireNotNull(view.accessibilityNodeProvider)
            val node = provider.createAccessibilityNodeInfo(semantic.id)
            assertNotNull("Missing exported accessibility node for $tag", node)
            val exported = requireNotNull(node)
            try {
                assertEquals("Exported resource ID", tag, exported.viewIdResourceName)
                assertTrue("Incorrect exported control state for $tag", predicate(exported))
            } finally {
                @Suppress("DEPRECATION")
                exported.recycle()
            }
        } finally {
            root.forceAccessibilityForTesting(false)
        }
    }
}
