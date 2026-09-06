package com.smartnotebook.service.recording

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.runner.permission.PermissionRequester
import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

@SuppressLint("RestrictedApi")
@RunWith(AndroidJUnit4::class)
class RecordingForegroundServiceInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val outputDirectory = File(context.filesDir, "recording")

    private val permissionRequester = PermissionRequester()

    @Before
    fun grantRecordingPermissions() {
        permissionRequester.addPermissions(*requiredPermissions())
        permissionRequester.requestPermissions()
        awaitPermissionsReady()
    }

    @Test
    fun foregroundServiceSupportsStartPauseResumeAndStop() {
        deleteOutputs()

        val control = startAndAwaitControl()
        awaitState(control) { it is RecordingSessionState.Recording }
        assertNotificationActive()

        runBlocking { delay(1_500L) }
        sendAction(RecordingForegroundService.ACTION_PAUSE)
        awaitState(control) { it is RecordingSessionState.Paused }

        sendAction(RecordingForegroundService.ACTION_RESUME)
        awaitState(control) { it is RecordingSessionState.Recording }
        runBlocking { delay(1_500L) }

        sendAction(RecordingForegroundService.ACTION_STOP)
        awaitState(control) { it is RecordingSessionState.Idle }

        val segments = outputDirectory.listFiles().orEmpty()
        assertThat(segments.size).isAtLeast(2)
        segments.forEach { file ->
            assertThat(M4aSegmentValidator.validate(file)).isNotNull()
        }
    }

    @After
    fun stopService() {
        sendAction(RecordingForegroundService.ACTION_STOP)
        deleteOutputs()
    }

    private fun startAndAwaitControl(): RecordingControl {
        context.startForegroundService(
            Intent(context, RecordingForegroundService::class.java)
                .setAction(RecordingForegroundService.ACTION_START),
        )
        return awaitControl()
    }

    private fun sendAction(action: String) {
        if (action == RecordingForegroundService.ACTION_RESUME) {
            context.startForegroundService(intentFor(action))
        } else {
            context.startService(intentFor(action))
        }
    }

    private fun intentFor(action: String): Intent =
        Intent(context, RecordingForegroundService::class.java).setAction(action)

    private fun awaitControl(): RecordingControl =
        runBlocking {
            val control: RecordingControl =
                withTimeout(10_000L) {
                    while (true) {
                        RecordingControllerRegistry.current()?.let { candidate ->
                            return@withTimeout candidate
                        }
                        delay(50L)
                    }
                    error("control-not-registered")
                }
            control
        }

    private fun awaitState(
        control: RecordingControl,
        predicate: (RecordingSessionState) -> Boolean,
    ) {
        runBlocking {
            withTimeout(15_000L) {
                control.state.first { predicate(it) }
            }
        }
    }

    private fun assertNotificationActive() {
        val manager = context.getSystemService(NotificationManager::class.java)
        val found =
            runBlocking {
                withTimeoutOrNull(15_000L) {
                    while (true) {
                        val active = manager.activeNotifications.orEmpty()
                        if (active.any { it.id == RecordingForegroundService.NOTIFICATION_ID }) {
                            return@withTimeoutOrNull true
                        }
                        delay(100L)
                    }
                } ?: false
            }
        val active = manager.activeNotifications.orEmpty()
        val channels = manager.getNotificationChannels().map { channel -> channel.id }
        val activeMatch = active.any { it.id == RecordingForegroundService.NOTIFICATION_ID }
        if (found == false && activeMatch == false) {
            error("active=${active.map { it.id }} channels=$channels")
        }
    }

    private fun deleteOutputs() {
        outputDirectory.listFiles().orEmpty().forEach { file ->
            file.delete()
        }
    }

    private fun requiredPermissions(): Array<String> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            arrayOf(Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS)
        } else {
            arrayOf(Manifest.permission.RECORD_AUDIO)
        }

    private fun awaitPermissionsReady() {
        val manager = context.getSystemService(NotificationManager::class.java)
        val deadline = System.currentTimeMillis() + 5_000L
        while (System.currentTimeMillis() < deadline) {
            val microphoneGranted =
                context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) ==
                    PackageManager.PERMISSION_GRANTED
            val notificationsReady =
                Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                    (
                        context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) ==
                            PackageManager.PERMISSION_GRANTED &&
                            manager.areNotificationsEnabled()
                    )
            if (microphoneGranted && notificationsReady) {
                return
            }
            Thread.sleep(100L)
        }
        error("permissions-not-ready")
    }
}
