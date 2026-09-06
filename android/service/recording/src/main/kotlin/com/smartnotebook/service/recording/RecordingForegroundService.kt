package com.smartnotebook.service.recording

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.Handler
import android.os.IBinder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import java.io.File
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

@Suppress("TooManyFunctions")
public class RecordingForegroundService : Service() {
    private lateinit var permissionChecker: RecordingPermissionChecker
    private lateinit var controller: RecordingSessionController
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val controlExecutor: ExecutorService =
        Executors.newSingleThreadExecutor { runnable -> Thread(runnable, "recording-control") }
    private var notificationJob: Job? = null
    private var isForeground = false
    private val binder = LocalBinder()

    inner class LocalBinder : Binder() {
        val control: RecordingControl
            get() = controller
    }

    override fun onCreate() {
        permissionChecker = AndroidRecordingPermissionChecker(this)
        controller =
            RecordingSessionController(
                permissionChecker = permissionChecker,
                engine = NativeAacLcRecordingEngine(),
                clock = { System.currentTimeMillis() },
                outputDirectoryProvider = { File(filesDir, RECORDING_DIRECTORY) },
            )
        RecordingControllerRegistry.register(controller)
        ensureNotificationChannel()
        notificationJob =
            scope.launch {
                controller.state.collect { state ->
                    if (isForeground) {
                        updateNotification(state)
                    }
                }
            }
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        val action = intent?.action ?: ACTION_START
        when (action) {
            ACTION_START -> handleStart()
            ACTION_PAUSE -> execute { controller.pause() }
            ACTION_RESUME -> handleResume()
            ACTION_STOP -> handleStop()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        notificationJob?.cancel()
        scope.cancel()
        controlExecutor.shutdownNow()
        if (::controller.isInitialized) {
            RecordingControllerRegistry.unregister(controller)
        }
    }

    override fun onBind(intent: Intent): IBinder = binder

    private fun handleStart() {
        if (permissionChecker.requiredPermissionCode() != null) {
            execute { controller.start() }
            return
        }
        startForegroundWithMicrophone()
        execute { controller.start() }
    }

    private fun handleResume() {
        if (permissionChecker.requiredPermissionCode() != null) {
            execute { controller.resume() }
            return
        }
        startForegroundWithMicrophone()
        execute { controller.resume() }
    }

    private fun handleStop() {
        execute {
            controller.stop()
            Handler(getMainLooper()).post {
                stopForegroundAndRemove()
                stopSelf()
            }
        }
    }

    private fun execute(block: () -> Unit) {
        controlExecutor.execute { block() }
    }

    private fun startForegroundWithMicrophone() {
        val notification = buildNotification(controller.state.value)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        isForeground = true
        updateNotification(controller.state.value)
    }

    private fun stopForegroundAndRemove() {
        if (isForeground) {
            stopForeground(STOP_FOREGROUND_REMOVE)
            isForeground = false
        }
    }

    private fun updateNotification(state: RecordingSessionState) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIFICATION_ID, buildNotification(state))
    }

    private fun ensureNotificationChannel() {
        val manager = getSystemService(NotificationManager::class.java)
        val channel =
            NotificationChannel(
                CHANNEL_ID,
                getString(R.string.recording_notification_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            )
        channel.description = getString(R.string.recording_notification_channel_description)
        channel.setShowBadge(false)
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(state: RecordingSessionState): Notification {
        val builder =
            Notification
                .Builder(this, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle(titleFor(state))
                .setContentText(getString(R.string.recording_notification_text))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setAutoCancel(false)
                .setCategory(Notification.CATEGORY_SERVICE)
                .setVisibility(Notification.VISIBILITY_PUBLIC)
        return builder.build()
    }

    private fun titleFor(state: RecordingSessionState): String =
        when (state) {
            is RecordingSessionState.Preparing ->
                getString(R.string.recording_notification_title_preparing)
            is RecordingSessionState.Recording ->
                getString(R.string.recording_notification_title_recording)
            is RecordingSessionState.Paused ->
                getString(R.string.recording_notification_title_paused)
            is RecordingSessionState.Stopping ->
                getString(R.string.recording_notification_title_stopping)
            is RecordingSessionState.PermissionRequired ->
                getString(R.string.recording_notification_title_attention)
            is RecordingSessionState.Failed ->
                getString(R.string.recording_notification_title_attention)
            is RecordingSessionState.Idle ->
                getString(R.string.recording_notification_title_idle)
        }

    public companion object {
        public const val ACTION_START: String = "com.smartnotebook.service.recording.action.START"
        public const val ACTION_PAUSE: String = "com.smartnotebook.service.recording.action.PAUSE"
        public const val ACTION_RESUME: String = "com.smartnotebook.service.recording.action.RESUME"
        public const val ACTION_STOP: String = "com.smartnotebook.service.recording.action.STOP"
        public const val NOTIFICATION_ID: Int = 7001

        private const val CHANNEL_ID: String = "recording"
        private const val RECORDING_DIRECTORY: String = "recording"
    }
}
