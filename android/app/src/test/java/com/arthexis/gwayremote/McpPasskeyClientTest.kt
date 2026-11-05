package com.arthexis.gwayremote

import org.junit.Assert.*
import org.junit.Test

class McpPasskeyClientTest {
    @Test fun intentOnlyRequestsCombinedScopesAndShortLifetime() {
        val intent = McpPasskeyClient.issueIntent()
        assertEquals("issue_mcp_bearer", intent.getString("action"))
        val scopes = intent.getJSONArray("scopes")
        assertEquals(2, scopes.length())
        assertEquals("gway:execute", scopes.getString(0))
        assertEquals("gway:read", scopes.getString(1))
        assertEquals(86400, intent.getInt("lifetime_seconds"))
        assertTrue(Regex("[0-9a-f]{32}").matches(intent.getString("request_id")))
        assertNotEquals(McpPasskeyClient.issueIntent().getString("request_id"),
            intent.getString("request_id"))
    }

    @Test fun revocationRequiresExactBearerIdentifier() {
        val intent = McpPasskeyClient.revokeIntent("a".repeat(24))
        assertEquals("revoke_mcp_bearer", intent.getString("action"))
        assertEquals("a".repeat(24), intent.getString("key_id"))
        for (bad in listOf("", "A".repeat(24), "../secrets", "f".repeat(23),
            "f".repeat(25), "g".repeat(24))) {
            try {
                McpPasskeyClient.revokeIntent(bad)
                fail("Accepted invalid bearer ID")
            } catch (_: IllegalArgumentException) { }
        }
    }

    @Test fun principalAndEndpointCannotBeArbitrary() {
        assertEquals("https://remote.arthexis.com", McpPasskeyClient.RP_ORIGIN)
        assertEquals("remote.arthexis.com", McpPasskeyClient.RP_ID)
        assertTrue(McpPasskeyClient.validPrincipal("admin_001"))
        for (bad in listOf("", "admin/sudo", "with whitespace",
            "x".repeat(129), "https://evil.example", "../watchtower")) {
            assertFalse(McpPasskeyClient.validPrincipal(bad))
        }
        assertNotNull(FeatureRegistry.get("mcp-access"))
        assertNull(FeatureRegistry.get("mcp-access")?.operation)
    }
}
