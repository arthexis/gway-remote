package com.arthexis.gwayremote.features.liturgia

import org.junit.Assert.*
import org.junit.Test

class LiturgiaModelsTest {
    @Test fun defaultEditionIsDhh() {
        assertEquals("spanishdhh", DEFAULT_EDITION)
    }

    @Test fun rangesAreBoundedAndExplicit() {
        assertEquals(1..1, parseRange("1"))
        assertEquals(1..10, parseRange("1-10"))
        assertNull(parseRange("10-1"))
        assertNull(parseRange("0"))
        assertNull(parseRange("1-201"))
        assertNull(parseRange("1,2"))
    }

    @Test fun searchRejectsUnboundedOrConflictingInputs() {
        assertTrue(SearchRequest("amor").valid())
        assertTrue(SearchRequest("amor", testament = "DEU").valid())
        assertTrue(SearchRequest("am*", mode = "wildcard").valid())
        assertFalse(SearchRequest("").valid())
        assertFalse(SearchRequest("x".repeat(161)).valid())
        assertFalse(SearchRequest("a**", mode = "wildcard").valid())
        assertFalse(SearchRequest("amor", testament = "NT", bookId = "JHN").valid())
    }

    @Test fun referencesPreserveBookIdentity() {
        assertEquals("DAG 13:1", Verse("DAG", 13, 1, null).reference)
    }
    @Test fun savedPassagesContainOnlyValidatedReferences() {
        val saved = SavedPassage("spanishdhh", Passage("JHN", 3, 16, 17))
        assertEquals(saved, SavedPassage.decode(saved.encode()))
        assertEquals("spanishdhh|JHN|3|16|17", saved.encode())
        assertNull(SavedPassage.decode("spanishdhh|JHN|3|17|16"))
        assertNull(SavedPassage.decode("spanishdhh|JHN|3|16|17|extra"))
    }
}
