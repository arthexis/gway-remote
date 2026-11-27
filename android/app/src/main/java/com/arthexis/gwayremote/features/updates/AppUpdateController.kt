package com.arthexis.gwayremote.features.updates

import com.arthexis.gwayremote.*

import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * App-owned APK update lifecycle. Install authorization belongs to Android's
 * existing platform contract, not to a remote module or backend command.
 */
internal data class AppUpdateController(
    val available: AvailableUpdate?,
    val status: String,
    val running: Boolean,
    val apkReady: Boolean,
    val check: () -> Unit,
    val download: () -> Unit,
    val install: () -> Unit
)

@Composable
internal fun rememberAppUpdateController(): AppUpdateController {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { /* Background checks continue; alerts require permission. */ }
    LaunchedEffect(Unit) {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            androidx.core.content.ContextCompat.checkSelfPermission(
                context, android.Manifest.permission.POST_NOTIFICATIONS
            ) != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
    }
    val installedCode = if (android.os.Build.VERSION.SDK_INT >= 33)
        context.packageManager.getPackageInfo(context.packageName, android.content.pm.PackageManager.PackageInfoFlags.of(0)).longVersionCode
    else @Suppress("DEPRECATION") context.packageManager.getPackageInfo(context.packageName, 0).longVersionCode
    var update by remember { mutableStateOf<AvailableUpdate?>(null) }
    var updateState by remember { mutableStateOf(CompanionUpdateState()) }
    val updateStatus = updateState.status
    val updating = updateState.running
    var apk by remember {
        mutableStateOf(java.io.File(context.cacheDir, "gway-remote-update.apk").takeIf { it.isFile })
    }
    var installPermissionState by remember { mutableStateOf(CompanionInstallPermissionState()) }

    fun launchInstaller() {
        val candidate = update
        val file = apk
        if (candidate == null || file == null) {
            updateState = updateState.status("No verified update available; download it again")
            return
        }
        if (updating) return
        updateState = updateState.started("Checking downloaded APK…")
        scope.launch {
            CompanionUpdateTransfer.install(
                verify = { withContext(Dispatchers.IO) { AppUpdater.verifyDownloadedApk(context, file, candidate) } },
                launch = { AppUpdater.install(context, file) },
                onStatus = { updateState = updateState.status(it) },
                onFinished = { updateState = updateState.finished() }
            )
        }
    }

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (installPermissionState.awaitingResult) {
            val outcome = installPermissionState.result(AppUpdater.canInstall(context))
            installPermissionState = outcome.state
            if (outcome.launchInstaller) launchInstaller()
            else outcome.status?.let { updateState = updateState.status(it) }
        }
    }

    fun requestInstall() {
        if (updating) return
        if (!AppUpdater.canInstall(context)) {
            installPermissionState = installPermissionState.requested()
            updateState = updateState.status("Grant installation permission, then return to GWay Remote")
            try {
                permissionLauncher.launch(AppUpdater.installPermissionIntent(context))
            } catch (e: Exception) {
                val outcome = installPermissionState.launchFailed(e.message)
                installPermissionState = outcome.state
                outcome.status?.let { updateState = updateState.status(it) }
            }
        } else launchInstaller()
    }

    fun checkUpdates() {
        if (updateState.running) return
        updateState = updateState.started("Checking releases…")
        scope.launch {
            CompanionUpdateCheck.run(
                check = { withContext(Dispatchers.IO) { AppUpdater.check(installedCode) } },
                onUpdate = { update = it },
                onStatus = { updateState = updateState.status(it) },
                onFinished = { updateState = updateState.finished() }
            )
        }
    }

    fun downloadUpdate() {
        val candidate = update ?: return
        if (updating) return
        updateState = updateState.started("Downloading and verifying…")
        scope.launch {
            CompanionUpdateTransfer.download(
                transfer = { withContext(Dispatchers.IO) { AppUpdater.download(context, candidate) } },
                onDownloaded = { apk = it },
                onStatus = { updateState = updateState.status(it) },
                onFinished = { updateState = updateState.finished() },
                requestInstall = { requestInstall() }
            )
        }
    }
    LaunchedEffect(Unit) { checkUpdates() }
    return AppUpdateController(
        available = update, status = updateState.status, running = updating,
        apkReady = apk?.isFile == true,
        check = ::checkUpdates, download = ::downloadUpdate, install = ::requestInstall
    )
}
