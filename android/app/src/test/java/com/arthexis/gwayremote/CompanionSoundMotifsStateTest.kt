package com.arthexis.gwayremote

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class CompanionSoundMotifsStateTest {
    @Test fun initialCatalogIsEmpty() {
        assertTrue(CompanionSoundMotifsState().available.isEmpty())
    }

    @Test fun responsePreservesMotifOrderAndDuplicates() {
        val state = CompanionSoundMotifsState().loaded(
            JSONObject("""{"result":{"motifs":["notice","woodpecker","notice"]}}""")
        )
        assertEquals(listOf("notice", "woodpecker", "notice"), state.available)
    }

    @Test fun missingResultAndMissingMotifsClearCatalog() {
        val initial = CompanionSoundMotifsState(listOf("old"))
        assertTrue(initial.loaded(JSONObject("{}")).available.isEmpty())
        assertTrue(initial.loaded(JSONObject("""{"result":{}}""")).available.isEmpty())
    }

    @Test fun failedRequestClearsPreviousCatalog() {
        val state = CompanionSoundMotifsState(listOf("old")).failed()
        assertTrue(state.available.isEmpty())
    }

    @Test fun malformedEntryPropagatesToExistingCatchHandler() {
        try {
            CompanionSoundMotifsState().loaded(JSONObject("""{"result":{"motifs":[null]}}"""))
            fail("Expected invalid motif entry")
        } catch (_: org.json.JSONException) {
            // CompanionScreen catches the same error and clears the catalog.
        }
    }

    @Test fun loadedResponseReplacesPreviousCatalog() {
        val state = CompanionSoundMotifsState(listOf("old")).loaded(
            JSONObject("""{"result":{"motifs":["new"]}}""")
        )
        assertEquals(listOf("new"), state.available)
    }
}
