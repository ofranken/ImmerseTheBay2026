package com.scrapp.app.glasses

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.IBinder
import androidx.core.content.ContextCompat
import com.scrapp.app.MainActivity

/**
 * Foreground service that keeps the process (and the glasses session in [GlassesManager])
 * alive while Scrapp is "armed" and the phone is locked. Type connectedDevice for the glasses,
 * plus location so GPS tags still work in the background.
 */
class GlassesService : Service() {

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, "Scrapbooking", NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val notification = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setContentTitle("Scrapp is listening")
            .setContentText("Say \"scrapbook that\" or press the capture button")
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        var types = ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            types = types or ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        }
        startForeground(NOTIFICATION_ID, notification, types)
        return START_STICKY
    }

    companion object {
        private const val CHANNEL = "scrapp_glasses"
        private const val NOTIFICATION_ID = 41

        fun start(ctx: Context) = ContextCompat.startForegroundService(ctx, Intent(ctx, GlassesService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, GlassesService::class.java))
    }
}
