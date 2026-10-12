package com.arthexis.gwayremote

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

data class AvailableUpdate(val version: String, val versionCode: Long, val url: String, val sha256: String, val size: Long)

object AppUpdater {
    private const val RELEASE_URL = "https://api.github.com/repos/arthexis/gway-remote/releases/latest"
    private const val MAX_APK_SIZE = 100L * 1024 * 1024

    private fun connection(url: String): HttpURLConnection {
        val target = URL(url)
        require(target.protocol == "https") { "HTTPS required" }
        return (target.openConnection() as HttpURLConnection).apply {
            connectTimeout = 10000
            readTimeout = 30000
            setRequestProperty("User-Agent", "GWayRemote-Android")
            instanceFollowRedirects = true
        }
    }

    fun check(installedCode: Long): AvailableUpdate? {
        val conn = connection(RELEASE_URL)
        try {
            require(conn.responseCode == 200) { "Release check HTTP ${conn.responseCode}" }
            val release = JSONObject(conn.inputStream.bufferedReader().use { it.readText() })
            require(!release.optBoolean("draft") && !release.optBoolean("prerelease")) { "No stable release" }
            val version = release.getString("tag_name").removePrefix("android-v")
            val assets = release.getJSONArray("assets")
            for (i in 0 until assets.length()) {
                val asset = assets.getJSONObject(i)
                if (asset.optString("name") != "gway-remote.apk") continue
                val digest = asset.optString("digest")
                require(digest.matches(Regex("sha256:[0-9a-fA-F]{64}"))) {
                    "Release APK is missing a SHA-256 digest"
                }
                val size = asset.getLong("size")
                require(size in 1..MAX_APK_SIZE) { "Invalid APK size" }
                val url = asset.getString("browser_download_url")
                val parsed = URL(url)
                require(parsed.protocol == "https" && parsed.host == "github.com" &&
                    parsed.path.startsWith("/arthexis/gway-remote/releases/download/") &&
                    parsed.path.endsWith("/gway-remote.apk")) { "Unexpected release URL" }
                // Release tags follow android-vMAJOR.MINOR.PATCH; versionCode is
                // monotonically bumped independently, so use release body metadata.
                val code = Regex("(?m)^Android-Version-Code: ([0-9]+)$")
                    .find(release.optString("body"))?.groupValues?.get(1)?.toLongOrNull()
                    ?: throw IllegalStateException("Release lacks Android-Version-Code metadata")
                return if (code > installedCode) AvailableUpdate(version, code, url, digest.substringAfter(":"), size) else null
            }
            throw IllegalStateException("Release has no gway-remote.apk asset")
        } finally { conn.disconnect() }
    }

    fun download(context: Context, update: AvailableUpdate): File {
        val output = File(context.cacheDir, "gway-remote-update.apk")
        val partial = File(context.cacheDir, "gway-remote-update.part")
        partial.delete()
        val conn = connection(update.url)
        try {
            require(conn.responseCode == 200) { "APK download HTTP ${conn.responseCode}" }
            val digest = MessageDigest.getInstance("SHA-256")
            var count = 0L
            conn.inputStream.use { input ->
                partial.outputStream().use { out ->
                    val buffer = ByteArray(32768)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        count += n
                        require(count <= update.size && count <= MAX_APK_SIZE) { "APK size exceeded" }
                        digest.update(buffer, 0, n)
                        out.write(buffer, 0, n)
                    }
                }
            }
            require(count == update.size) { "Incomplete APK download" }
            val actual = digest.digest().joinToString("") { "%02x".format(it) }
            require(actual.equals(update.sha256, ignoreCase = true)) { "APK checksum mismatch" }
            output.delete()
            require(partial.renameTo(output)) { "Unable to prepare APK" }
            return output
        } finally {
            conn.disconnect()
            partial.delete()
        }
    }

    fun canInstall(context: Context): Boolean =
        Build.VERSION.SDK_INT < 26 || context.packageManager.canRequestPackageInstalls()

    fun installPermissionIntent(context: Context): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"))

    fun verifyDownloadedApk(context: Context, apk: File, update: AvailableUpdate) {
        require(apk.isFile && apk.canRead()) { "Downloaded APK is missing; download it again" }
        require(apk.length() == update.size) { "Downloaded APK size changed; download it again" }
        val digest = MessageDigest.getInstance("SHA-256")
        apk.inputStream().use { input ->
            val buffer = ByteArray(32768)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        val actual = digest.digest().joinToString("") { "%02x".format(it) }
        require(actual.equals(update.sha256, ignoreCase = true)) {
            "Downloaded APK checksum changed; download it again"
        }
        @Suppress("DEPRECATION")
        val manager = context.packageManager
        val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES
                    else @Suppress("DEPRECATION") PackageManager.GET_SIGNATURES
        @Suppress("DEPRECATION")
        val archive = manager.getPackageArchiveInfo(apk.absolutePath, flags)
        require(archive != null && archive.packageName == context.packageName) {
            "Downloaded APK is not a GWay Remote installation package"
        }
        @Suppress("DEPRECATION")
        val installed = manager.getPackageInfo(context.packageName, flags)
        val sameSigner = if (Build.VERSION.SDK_INT >= 28) {
            val incoming = archive.signingInfo
            val current = installed.signingInfo
            incoming != null && current != null && incoming.signersMatchExactly(current)
        } else {
            @Suppress("DEPRECATION")
            val incoming = archive.signatures?.map { it.toCharsString() }?.toSet()
            @Suppress("DEPRECATION")
            val current = installed.signatures?.map { it.toCharsString() }?.toSet()
            !incoming.isNullOrEmpty() && incoming == current
        }
        require(sameSigner) {
            "APK signing certificate does not match the installed app"
        }
    }

    fun install(context: Context, apk: File) {
        check(canInstall(context)) { "Allow installation from GWay Remote in Android settings" }
        require(apk.isFile && apk.canRead()) { "Downloaded APK is missing; download it again" }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", apk)
        val intent = Intent(Intent.ACTION_INSTALL_PACKAGE).apply {
            data = uri
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
            clipData = android.content.ClipData.newUri(context.contentResolver, "GWay Remote update", uri)
        }
        context.startActivity(intent)
    }
}
