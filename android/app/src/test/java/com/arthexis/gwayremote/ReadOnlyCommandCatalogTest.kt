package com.arthexis.gwayremote

import org.json.JSONArray
import org.json.JSONException
import org.junit.Assert.*
import org.junit.Test

class ReadOnlyCommandCatalogTest {
    @Test fun preservesServerOrderAndDuplicates() {
        val entries = JSONArray("""[
          {"name":"status","read_only":true},
          {"name":"health","read_only":true,"arguments":{}},
          {"name":"status","read_only":true}
        ]""")
        assertEquals(listOf("status", "health", "status"), ReadOnlyCommandCatalog.names(entries))
    }

    @Test fun excludesWritesInputsAndMissingNames() {
        val entries = JSONArray("""[
          {"name":"deploy","read_only":false},
          {"name":"inspect","read_only":true,"arguments":{"node":"required"}},
          {"name":"visible","read_only":true,"arguments":{}},
          {"read_only":true},
          {"name":"","read_only":true},
          {"name":"unset"},
          {"name":"null-args","read_only":true,"arguments":null}
        ]""")
        assertEquals(listOf("visible", "null-args"), ReadOnlyCommandCatalog.names(entries))
    }

    @Test fun emptyArrayReturnsEmptyList() {
        assertTrue(ReadOnlyCommandCatalog.names(JSONArray()).isEmpty())
    }

    @Test fun malformedArrayElementPreservesJsonException() {
        try {
            ReadOnlyCommandCatalog.names(JSONArray("""[42]"""))
            fail("Expected JSONException")
        } catch (_: JSONException) {
            // The old adapter used getJSONObject and failed on invalid entries.
        }
    }
}
