package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class ApiExceptionTest {
    @Test fun upstreamErrorCodeIsReadable() {
        val exception = ApiException(502, "agent_invalid_contract")
        assertTrue(exception.message.orEmpty().contains("502"))
        assertTrue(exception.message.orEmpty().contains("agent_invalid_contract"))
    }

    @Test fun genericErrorRemainsUsefulWithoutBody() {
        assertEquals("Server returned HTTP 502", ApiException(502).message)
        assertEquals("Unauthorized: check your token", ApiException(401).message)
    }
}
