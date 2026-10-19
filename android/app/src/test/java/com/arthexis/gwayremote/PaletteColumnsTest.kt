package com.arthexis.gwayremote

import org.junit.Assert.assertEquals
import org.junit.Test

class PaletteColumnsTest {
    @Test fun phoneWidthUsesFullWidthButtons() {
        assertEquals(1, paletteColumns(360f))
        assertEquals(1, paletteColumns(480f))
        assertEquals(1, paletteColumns(519f))
    }

    @Test fun tabletWidthAllowsMoreReadableColumns() {
        assertEquals(2, paletteColumns(520f))
        assertEquals(2, paletteColumns(800f))
        assertEquals(3, paletteColumns(840f))
    }
}
