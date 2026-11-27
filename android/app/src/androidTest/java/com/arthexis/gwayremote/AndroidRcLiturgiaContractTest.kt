package com.arthexis.gwayremote

import android.os.Build
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.arthexis.gwayremote.features.liturgia.*
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.After
import org.junit.Rule
import org.junit.Test
import java.time.LocalDate
import java.util.concurrent.CopyOnWriteArrayList

/** Hosted emulator only, fixed fake transport. No live Bible, account or network access. */
class AndroidRcLiturgiaContractTest {
    @get:Rule val rule = createComposeRule()
    private var isolated = false
    private val prefsName = "rc_liturgia_fixture_" + java.util.UUID.randomUUID()
    private lateinit var library: LiturgiaLocalLibrary
    private val restricted = "FIXTURE RESTRICTED TEXT"
    private val permitted = "FIXTURE PERMITTED TEXT"
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext

    @Before fun requireEmulator() {
        assumeTrue("Fixture suite requires an emulator", Build.HARDWARE in setOf("ranchu", "goldfish"))
        isolated = true
        library = LiturgiaLocalLibrary(context.getSharedPreferences(prefsName, 0))
    }

    @After fun clearFixtureState() {
        if (isolated) context.deleteSharedPreferences(prefsName)
    }

    private inner class Fixture : LiturgiaSource {
        val days = CopyOnWriteArrayList<Pair<LocalDate, String>>()
        val searches = CopyOnWriteArrayList<Int>()
        val reads = CopyOnWriteArrayList<Pair<String, Passage>>()
        override suspend fun analytics(edition: String) = BibleStats(1, 2)
        override suspend fun translations() = listOf(
            Edition("spanishdhh", "Fixture DHH", true), Edition("sblm", "Fixture permitted", true))
        override suspend fun books(edition: String) = listOf(BibleBook("GEN", "Fixture Genesis", "OT", listOf(1, 2)))
        override suspend fun readings(day: LocalDate, form: String, edition: String): DayReadings {
            days.add(day to form)
            return DayReadings(day, "Fixture celebration", form, "partial", "partial",
                listOf(Reading("first", "Fixture reading", "GEN 1:1", "text_available",
                    listOf(Passage("GEN", 1, 1, 1)), verses = listOf(Verse("GEN", 1, 1, restricted)))),
                listOf("Fixture source"))
        }
        override suspend fun verse(passage: Passage, edition: String, offset: Int): VersePage {
            reads.add(edition to passage)
            return VersePage(edition, true, listOf(Verse(passage.bookId, passage.chapter,
                passage.first ?: 1, if (edition == "spanishdhh") restricted else permitted)), 1, null)
        }
        override suspend fun search(request: SearchRequest, edition: String, offset: Int): VersePage {
            searches.add(offset)
            if (request.query == "offline") error("FIXTURE PRIVATE ERROR")
            return VersePage(edition, true, listOf(Verse("GEN", 1, if (offset == 0) 1 else 26,
                restricted)), 26, if (offset == 0) 25 else null)
        }
    }

    private fun click(label: String) {
        rule.onNodeWithText(label).performScrollTo().performClick()
    }

    @Test fun dayFormAndRightsBoundary() {
        val source = Fixture()
        rule.setContent { MaterialTheme { LiturgiaPanel(source, library) } }
        rule.onNodeWithText("Fixture celebration").assertExists()
        rule.onNodeWithText("Cobertura: partial").assertExists()
        rule.onNodeWithText(restricted, substring = true).assertDoesNotExist()
        val first = source.days.first().first
        click("›")
        rule.waitUntil(5000) { source.days.any { it.first == first.plusDays(1) } }
        rule.onNodeWithText(first.plusDays(1).toString()).assertExists()
        click("auto")
        rule.onNodeWithText("Propia").performClick()
        rule.waitUntil(5000) { source.days.any { it == (first.plusDays(1) to "proper") } }
        rule.onNodeWithText(restricted, substring = true).assertDoesNotExist()
    }

    @Test fun readerComparisonBookmarkAndHistory() {
        val source = Fixture()
        rule.setContent { MaterialTheme { LiturgiaPanel(source, library) } }
        click("Biblia")
        click("Seleccionar")
        rule.onNodeWithText("Fixture Genesis").performClick()
        click("Consultar")
        rule.onNodeWithText("GEN 1:1").assertExists()
        rule.onNodeWithText(restricted, substring = true).assertDoesNotExist()
        click("Sin comparación")
        rule.onNodeWithText("Fixture permitted").performClick()
        rule.onNodeWithText(permitted).assertExists()
        rule.onNodeWithText(restricted, substring = true).assertDoesNotExist()
        assertTrue(source.reads.any { it.first == "sblm" })
        click("Guardar")
        rule.onNodeWithText("Quitar marcador").assertExists()
        rule.runOnIdle {
            assertEquals(listOf(SavedPassage("spanishdhh", Passage("GEN", 1))), library.bookmarks())
            assertTrue(library.history().contains(SavedPassage("spanishdhh", Passage("GEN", 1))))
        }
        click("Quitar marcador")
        rule.onNodeWithText("Guardar").assertExists()
        click("Lectura ampliada")
        rule.onNodeWithText("Tamaño normal").assertExists()
        click("Borrar historial")
        rule.runOnIdle {
            assertTrue(library.bookmarks().isEmpty())
            assertTrue(library.history().isEmpty())
        }
    }

    @Test fun searchPaginationAndSanitizedError() {
        val source = Fixture()
        rule.setContent { MaterialTheme { LiturgiaPanel(source, library) } }
        click("Buscar")
        rule.onAllNodesWithText("Buscar")[1].assertIsNotEnabled()
        rule.onNodeWithText("Palabra o frase").performScrollTo().performTextInput("amor")
        rule.onAllNodesWithText("Buscar")[1].performScrollTo().performClick()
        rule.onNodeWithText("GEN 1:1").assertExists()
        rule.onNodeWithText(restricted, substring = true).assertDoesNotExist()
        click("Más")
        rule.waitUntil(5000) { source.searches.contains(25) }
        rule.onNodeWithText("GEN 1:26").assertExists()
        rule.onNodeWithText("GEN 1:1").assertDoesNotExist()
        rule.onNodeWithText("Palabra o frase").performScrollTo().performTextReplacement("offline")
        rule.onAllNodesWithText("Buscar")[1].performScrollTo().performClick()
        rule.onNodeWithText("Consulta no disponible.").assertExists()
        rule.onNodeWithText("FIXTURE PRIVATE ERROR", substring = true).assertDoesNotExist()
        rule.onNodeWithText("GEN 1:26").assertDoesNotExist()
        assertEquals(listOf(0, 25, 0), source.searches.toList())
    }
}
