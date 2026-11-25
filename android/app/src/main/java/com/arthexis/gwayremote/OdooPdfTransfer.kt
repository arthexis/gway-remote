package com.arthexis.gwayremote

import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Authenticated, bounded binary download from the same GWay Remote HTTPS API.
 * Unlike DownloadManager, this never places the bearer token in a URL.
 */
object OdooPdfTransfer {
    // Odoo's PDF CLI adds a Spanish prefix and sanitizes the native order name.
    // Accept only this exact deterministic name, or the legacy exact name.
    internal fun matchesOfficialFilename(actual: String, orderName: String): Boolean {
        val safe = java.text.Normalizer.normalize(orderName, java.text.Normalizer.Form.NFC)
            .map { if (it.isLetterOrDigit() || it in " _-.()") it else '_' }
            .joinToString("").replace(Regex(" +"), " ").trim(' ', '.', '_')
        val native = if (safe.startsWith("Cotización ", ignoreCase = true)) safe else "Cotización $safe"
        return actual == orderName + ".pdf" ||
            (safe.isNotBlank() && safe.length <= 128 && actual == native + ".pdf")
    }

    private const val MAX_PDF = 20L * 1024L * 1024L

    fun download(endpoint: String, token: String, orderId: Int, expectedName: String,
                 output: OutputStream): Long {
        require(orderId > 0 && expectedName.isNotBlank())
        val base = URL(endpoint.trimEnd('/') + "/")
        require(base.protocol == "https" && base.userInfo == null && base.query == null && base.ref == null)
        require(token.isNotBlank())
        val url = URL(base, "api/v1/odoo/quotations/$orderId/pdf")
        require(url.host.equals(base.host, ignoreCase = true) && url.protocol == "https")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod = "GET"
        conn.instanceFollowRedirects = false
        conn.connectTimeout = 10000
        conn.readTimeout = 120000
        conn.setRequestProperty("Authorization", "Bearer $token")
        conn.setRequestProperty("Accept", "application/pdf")
        try {
            val status = conn.responseCode
            if (status !in 200..299) throw ApiException(status)
            require(conn.contentType?.substringBefore(';')?.trim()?.lowercase() == "application/pdf") {
                "Server did not send a PDF"
            }
            val header = conn.getHeaderField("Content-Disposition") ?: ""
            val encoded = header.substringAfter("filename*=UTF-8''", "")
                .substringBefore(';')
            require(encoded.isNotBlank()) { "Missing official quotation filename" }
            val actual = java.net.URLDecoder.decode(encoded.replace("+", "%2B"), "UTF-8")
            require(matchesOfficialFilename(actual, expectedName)) {
                "Quotation name changed in Odoo; refresh and download again"
            }
            val sizeHint = conn.contentLengthLong
            require(sizeHint in 1024..MAX_PDF) { "Unexpected PDF size" }
            var count = 0L
            var first = ByteArray(5)
            var firstCount = 0
            val trailer = java.io.ByteArrayOutputStream()
            conn.inputStream.use { input ->
                val buffer = ByteArray(32768)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    count += n
                    require(count <= MAX_PDF && count <= sizeHint) { "PDF exceeded advertised size" }
                    if (firstCount < 5) {
                        val copy = minOf(n, 5 - firstCount)
                        System.arraycopy(buffer, 0, first, firstCount, copy)
                        firstCount += copy
                    }
                    if (trailer.size() + n > 2048) {
                        val bytes = trailer.toByteArray()
                        trailer.reset()
                        val keep = (bytes.size + n - 2048).coerceAtLeast(0)
                        if (keep < bytes.size) trailer.write(bytes, keep, bytes.size - keep)
                        trailer.write(buffer, 0, n)
                        val joined = trailer.toByteArray()
                        if (joined.size > 2048) {
                            trailer.reset()
                            trailer.write(joined, joined.size - 2048, 2048)
                        }
                    } else trailer.write(buffer, 0, n)
                    output.write(buffer, 0, n)
                }
            }
            require(count == sizeHint && firstCount == 5 &&
                first.contentEquals("%PDF-".toByteArray(Charsets.US_ASCII)) &&
                trailer.toByteArray().toString(Charsets.ISO_8859_1).contains("%%EOF")) {
                "Incomplete or invalid PDF"
            }
            output.flush()
            return count
        } finally {
            conn.disconnect()
        }
    }
}
