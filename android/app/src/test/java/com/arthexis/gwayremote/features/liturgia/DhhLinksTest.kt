package com.arthexis.gwayremote.features.liturgia

import java.net.URLDecoder
import java.time.LocalDate
import org.junit.Assert.*
import org.junit.Test

class DhhLinksTest {
    @Test fun combinedLinkPreservesOrderAndCrossChapterRange() {
        val url = dhhUrl(listOf(
            DhhPassage("REV", 20, 1, 20, 4),
            DhhPassage("REV", 20, 11, 21, 2),
            DhhPassage("PSA", 84, 2, 84, 5),
            DhhPassage("PSA", 84, 7),
            DhhPassage("LUK", 21, 29, 21, 33)))
        assertEquals("https://www.biblegateway.com/passage/?search=Apocalipsis 20:1-4; Apocalipsis 20:11-21:2; Salmos 84:2-5; Salmos 84:7; Lucas 21:29-33&version=DHH",
            URLDecoder.decode(url!!, "UTF-8"))
    }

    @Test fun malformedRangesNeverOpenAnUnrelatedUrl() {
        assertNull(dhhUrl(listOf(DhhPassage("https://evil.example", 1, 1))))
        assertNull(dhhUrl(listOf(DhhPassage("GEN", 0, 1))))
        assertNull(dhhUrl(listOf(DhhPassage("GEN", 1, 9, 1, 2))))
        assertNull(dhhUrl(listOf(DhhPassage("GEN", 1, null, 1, 2))))
        assertNull(dhhUrl(listOf(DhhPassage("DAG", 13, 1))))
    }

    @Test fun deuterocanonicalsAreExplicitExternalCatalog() {
        assertEquals(setOf("TOB", "JDT", "WIS", "SIR", "BAR", "1MA", "2MA"), dhhOnlineBooks.map { it.id }.toSet())
        for (book in dhhOnlineBooks) {
            assertNotNull(dhhUrl(listOf(Passage(book.id, book.chapters.last()).asDhhPassage())))
        }
        assertTrue(dhhUrl(listOf(DhhPassage("SIR", 3, 1)))!!.contains("version=DHH"))
        assertFalse(mayDisplayText(DEFAULT_EDITION, true))
    }

    @Test fun completeSelectedFormRequiredEvenIfLocalTextIsMissing() {
        val reading = { role: String, bid: String -> Reading(role, role, "citation", "passage_unavailable",
            emptyList(), dhhPassages = listOf(DhhPassage(bid, 1, 1))) }
        val day = DayReadings(LocalDate.of(2026, 11, 27), null, "ordinary", "partial", "partial",
            listOf(reading("first", "TOB"), reading("psalm", "PSA"), reading("gospel", "LUK")), emptyList())
        assertNotNull(allDailyDhhUrl(day))
        assertNull(allDailyDhhUrl(day.copy(readings = day.readings.dropLast(1))))
        assertNull(allDailyDhhUrl(day.copy(readings = day.readings + reading("second", "unknown"))))
        assertNull(allDailyDhhUrl(day.copy(status = "stale")))
        assertNull(allDailyDhhUrl(day.copy(selectedForm = null)))
    }
}
