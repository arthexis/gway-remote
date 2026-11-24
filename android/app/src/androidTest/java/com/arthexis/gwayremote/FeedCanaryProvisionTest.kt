package com.arthexis.gwayremote

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.arthexis.gwayremote.features.feed.*
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import android.util.AtomicFile
import android.util.Base64

@RunWith(AndroidJUnit4::class)
class FeedCanaryProvisionTest {
    @Test fun privateSeedAndIsolatedHttps() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("gway_feed_usb") == "v1")
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        assertEquals(CANARY_PACKAGE, context.packageName)
        val seed = File(context.filesDir, ".gway-feed-once")
        val certificate = AtomicFile(File(context.noBackupFilesDir, CANARY_CERT_FILE))
        require(!certificate.baseFile.exists() && !File(certificate.baseFile.path + ".bak").exists() &&
            !File(certificate.baseFile.path + ".new").exists())
        try {
            require(seed.isFile && seed.length() in 1..12000)
            val raw = seed.readBytes()
            require(seed.delete())
            val bundle = JSONObject(raw.toString(Charsets.US_ASCII))
            raw.fill(0)
            require(bundle.keys().asSequence().toSet() == setOf("reader", "certificate"))
            val reader = bundle.getString("reader")
            require(validFeedToken(reader))
            val der = Base64.decode(bundle.getString("certificate"), Base64.NO_WRAP)
            require(der.size in 1..8192)
            val stream = certificate.startWrite()
            try { stream.write(der); certificate.finishWrite(stream) }
            catch (e: Exception) { certificate.failWrite(stream); throw e }
            loadCanaryCertificate(certificate.baseFile)
            // Keep the field-test bearer exclusively in memory. A process kill
            // cannot leave a usable persisted credential or overwrite user state.
            val page = runBlocking { FeedRepository(context).page(reader) }
            assertEquals(listOf("Synthetic feed canary"), page.items.map { it.title })
            val denied = runCatching {
                runBlocking { FeedRepository(context).page("gwr_" + "0".repeat(24) + "_invalid") }
            }.exceptionOrNull()
            assertTrue("Unrecognized bearer must be rejected", denied is FeedHttpError && denied.status == 401)
        } catch (_: Exception) {
            throw AssertionError("Isolated feed enrollment or HTTPS verification failed")
        } finally {
            if (seed.exists()) require(seed.delete())
            certificate.delete()
            require(!certificate.baseFile.exists())
        }
    }
}
