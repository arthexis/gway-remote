package com.arthexis.gwayremote

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Canary-only, operator-controlled USB credential handoff.
 *
 * The node provides the one-time secret to a private run-as file over ADB stdin,
 * never as a shell argument, UI text, build secret, or instrument argument.
 * The test consumes and deletes the file, encrypts via AndroidKeyStore, then
 * proves the real public HTTPS Mobile API accepts this device's bearer.
 */
@RunWith(AndroidJUnit4::class)
class MobileDeviceProvisionTest {
    @Test fun consumePrivateUsbCredentialAndVerifyHttps() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals("com.arthexis.gwayremote.canary", context.packageName)
        val source = File(context.filesDir, ".gway-mobile-token-once")
        assertTrue("One-time private credential missing", source.isFile && source.length() in 65..120)
        val payload = source.readBytes()
        assertTrue("Could not remove one-time credential", source.delete())
        val credential = payload.toString(Charsets.US_ASCII)
        payload.fill(0)
        assertTrue("Invalid device bearer format",
            Regex("gwymob1_[0-9a-f]{24}_[A-Za-z0-9_-]{43}").matches(credential))
        val store = SecretStore(context)
        try {
            store.endpoint = "https://remote.arthexis.com"
            store.token = credential
            val health = ApiClient(store.endpoint, store.token)
                .request("api/v1/health", timeoutMs = 10000)
            assertEquals("ok", health.getString("status"))
        } catch (_: Exception) {
            // No stranded usable credentials after a failed HTTPS smoke test.
            store.token = ""
            throw AssertionError("Mobile API authentication test failed")
        }
    }
}
