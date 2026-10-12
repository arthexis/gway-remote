package com.arthexis.gwayremote

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkerParameters
import androidx.work.WorkManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

internal object UpdateNotifications {
    const val CHANNEL_ID = "gway_app_updates"
    const val WORK_NAME = "gway-release-check"
    private const val NOTIFICATION_ID = 1001
    private const val LAST_NOTIFIED = "last_notified_version_code"

    fun schedule(context: Context) {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = PeriodicWorkRequestBuilder<UpdateCheckWorker>(6, TimeUnit.HOURS)
            .setConstraints(constraints)
            .build()
        WorkManager.getInstance(context).enqueueUniquePeriodicWork(
            WORK_NAME, ExistingPeriodicWorkPolicy.KEEP, request
        )
    }

    fun createChannel(context: Context) {
        if (Build.VERSION.SDK_INT >= 26) {
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "App updates", NotificationManager.IMPORTANCE_DEFAULT)
                    .apply { description = "New GWay Remote APK releases" }
            )
        }
    }

    fun showIfNew(context: Context, update: AvailableUpdate) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) return

        val preferences = context.getSharedPreferences("gway_update_notifications", Context.MODE_PRIVATE)
        if (update.versionCode <= preferences.getLong(LAST_NOTIFIED, 0)) return

        createChannel(context)
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("open_update", true)
        }
        val pendingIntent = PendingIntent.getActivity(
            context, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_download_done)
            .setContentTitle("GWay Remote update available")
            .setContentText("Version ${update.version} is ready to install")
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .build()
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, notification)
        preferences.edit().putLong(LAST_NOTIFIED, update.versionCode).apply()
    }
}

class UpdateCheckWorker(context: Context, parameters: WorkerParameters) :
    CoroutineWorker(context, parameters) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            @Suppress("DEPRECATION")
            val installed = applicationContext.packageManager
                .getPackageInfo(applicationContext.packageName, 0).longVersionCode
            AppUpdater.check(installed)?.let { UpdateNotifications.showIfNew(applicationContext, it) }
            Result.success()
        } catch (_: Exception) {
            Result.retry()
        }
    }
}
