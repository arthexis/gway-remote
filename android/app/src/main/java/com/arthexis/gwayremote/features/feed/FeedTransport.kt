package com.arthexis.gwayremote.features.feed

import android.content.Context
import java.io.ByteArrayInputStream
import java.io.File
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

internal const val CANARY_PACKAGE = "com.arthexis.gwayremote.canary"
internal const val PRODUCTION_PACKAGE = "com.arthexis.gwayremote"
internal const val CANARY_FEED_ORIGIN = "https://127.0.0.1:18443"
internal const val CANARY_CERT_FILE = "feed-canary-cert.der"

internal fun feedOrigin(packageName: String): String = when (packageName) {
    PRODUCTION_PACKAGE -> FEED_ORIGIN
    CANARY_PACKAGE -> CANARY_FEED_ORIGIN
    else -> throw SecurityException("Unsupported feed application")
}

internal fun feedTarget(packageName: String, before: Long?): URL {
    require(before == null || before > 0)
    return URL("${feedOrigin(packageName)}/api/feed/events?limit=$PAGE_SIZE" +
        (before?.let { "&before=$it" } ?: ""))
}

internal fun loadCanaryCertificate(file: File): X509Certificate {
    val bytes = file.inputStream().use { input ->
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(1024)
        while (true) {
            val n = input.read(buffer)
            if (n < 0) break
            require(output.size() + n <= 8192)
            output.write(buffer, 0, n)
        }
        output.toByteArray()
    }
    val input = ByteArrayInputStream(bytes)
    val cert = CertificateFactory.getInstance("X.509").generateCertificate(input) as X509Certificate
    require(input.available() == 0 && cert.encoded.contentEquals(bytes)) { "Expected a single DER certificate" }
    cert.checkValidity()
    require(cert.subjectAlternativeNames.orEmpty().any { it.size >= 2 && it[0] == 7 && it[1] == "127.0.0.1" })
    return cert
}

/** Trust only the exact provisioned leaf, never the system CA store in canary. */
internal fun pinnedTrustManager(cert: X509Certificate): X509TrustManager {
    val anchors = KeyStore.getInstance(KeyStore.getDefaultType()).apply {
        load(null, null)
        setCertificateEntry("feed-canary", cert)
    }
    val tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm()).apply { init(anchors) }
    val delegate = tmf.trustManagers.filterIsInstance<X509TrustManager>().single()
    return object : X509TrustManager {
        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf(cert)
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
            throw CertificateException("Client certificates not accepted")
        }
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isEmpty() || !MessageDigest.isEqual(cert.encoded, chain[0].encoded))
                throw CertificateException("Canary certificate mismatch")
            cert.checkValidity()
            delegate.checkServerTrusted(chain, authType)
        }
    }
}

internal class FeedTransport(private val context: Context) {
    val isCanary: Boolean = context.packageName == CANARY_PACKAGE
    private fun certificate(): X509Certificate =
        loadCanaryCertificate(File(context.noBackupFilesDir, CANARY_CERT_FILE))

    fun cacheIdentity(): String {
        val origin = feedOrigin(context.packageName)
        if (!isCanary) return origin
        val digest = MessageDigest.getInstance("SHA-256").digest(certificate().encoded)
            .joinToString("") { "%02x".format(it.toInt() and 255) }
        return "$origin/$digest"
    }

    fun connection(before: Long?): HttpsURLConnection {
        // Resolve/validate the isolated trust before any connection is opened.
        val factory = if (isCanary) SSLContext.getInstance("TLS").apply {
            init(null, arrayOf(pinnedTrustManager(certificate())), null)
        }.socketFactory else null
        val result = feedTarget(context.packageName, before)
            .openConnection(java.net.Proxy.NO_PROXY) as HttpsURLConnection
        if (factory != null) result.sslSocketFactory = factory
        // Default hostname verification stays active. Never follow redirects.
        result.instanceFollowRedirects = false
        return result
    }
}
