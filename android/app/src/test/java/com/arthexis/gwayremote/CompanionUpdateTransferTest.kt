package com.arthexis.gwayremote

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class CompanionUpdateTransferTest {
    @Test fun successfulDownloadFinishesBeforeInstallRequest() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateTransfer.download(
            { events.add("transfer"); "verified.apk" },
            { events.add("file:$it") },
            { events.add(it) },
            { events.add("finished") },
            { events.add("request-install") }
        )
        assertEquals(listOf("transfer", "file:verified.apk", "Download verified; ready to install",
            "finished", "request-install"), events)
    }

    @Test fun failedDownloadNeverRequestsInstallation() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateTransfer.download<String>(
            { throw IllegalStateException("offline") }, { events.add("file") },
            { events.add(it) }, { events.add("finished") }, { events.add("install") }
        )
        assertEquals(listOf("offline", "finished"), events)
    }

    @Test fun downloadUsesOriginalFallback() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateTransfer.download<String>(
            { throw IllegalStateException() }, {}, { events.add(it) },
            { events.add("finished") }, { events.add("install") }
        )
        assertEquals(listOf("Update failed", "finished"), events)
    }

    @Test fun installVerifiesBeforeLaunchingAndFinishes() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateTransfer.install(
            { events.add("verify") }, { events.add("launch") },
            { events.add(it) }, { events.add("finished") }
        )
        assertEquals(listOf("verify", "launch",
            "Android installer requested. Confirm the update in the system dialog.", "finished"), events)
    }

    @Test fun verificationFailurePreventsInstallerLaunch() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateTransfer.install(
            { throw IllegalArgumentException("bad digest") }, { events.add("launch") },
            { events.add(it) }, { events.add("finished") }
        )
        assertEquals(listOf("Installation could not start: bad digest", "finished"), events)
    }

    @Test fun installerFailureUsesExceptionTypeFallback() = runBlocking {
        val events = mutableListOf<String>()
        CompanionUpdateTransfer.install(
            {}, { throw IllegalStateException() }, { events.add(it) },
            { events.add("finished") }
        )
        assertEquals(listOf("Installation could not start: IllegalStateException", "finished"), events)
    }
}
