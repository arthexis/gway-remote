package com.arthexis.gwayremote

import org.junit.Assert.assertThrows
import org.junit.Test

class ApiClientTest {
    @Test fun rejectsPlaintext() {
        assertThrows(IllegalArgumentException::class.java) { ApiClient("http://localhost:8765", "token") }
    }
    @Test fun rejectsMissingToken() {
        assertThrows(IllegalArgumentException::class.java) { ApiClient("https://example.com", "") }
    }
    @Test fun acceptsHttps() {
        ApiClient("https://example.com", "test")
    }
}
