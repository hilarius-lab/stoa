package com.smartnotebook.service.recording

import com.google.common.truth.Truth.assertThat
import com.smartnotebook.core.model.ClientErrorCode
import org.junit.Test
import java.io.File

class RecordingSessionControllerTest {
    private val permissionChecker = FakePermissionChecker()
    private val engine = FakeEngine()
    private val controller =
        RecordingSessionController(
            permissionChecker = permissionChecker,
            engine = engine,
            clock = { 123L },
            outputDirectoryProvider = { File("target") },
        )

    @Test
    fun initialStateIsIdle() {
        assertThat(controller.state.value).isEqualTo(RecordingSessionState.Idle)
    }

    @Test
    fun startWithGrantedPermissionsTransitionsToRecording() {
        controller.start()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Recording("TEST_SOURCE", 123L))
        assertThat(engine.startCount).isEqualTo(1)
    }

    @Test
    fun startWithDeniedMicrophonePermissionReportsPermissionRequired() {
        permissionChecker.required = ClientErrorCode.MIC_PERMISSION_REQUIRED

        controller.start()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.PermissionRequired(ClientErrorCode.MIC_PERMISSION_REQUIRED))
        assertThat(engine.startCount).isEqualTo(0)
    }

    @Test
    fun startWithDeniedNotificationPermissionReportsPermissionRequired() {
        permissionChecker.required = ClientErrorCode.NOTIFICATION_PERMISSION_REQUIRED

        controller.start()

        assertThat(controller.state.value)
            .isEqualTo(
                RecordingSessionState.PermissionRequired(ClientErrorCode.NOTIFICATION_PERMISSION_REQUIRED),
            )
        assertThat(engine.startCount).isEqualTo(0)
    }

    @Test
    fun startWithEngineFailureTransitionsToFailed() {
        engine.startResult = RecordingEngineResult.Failure(ClientErrorCode.ENCODER_FAILED, "encoder")

        controller.start()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Failed(ClientErrorCode.ENCODER_FAILED, "encoder"))
    }

    @Test
    fun pauseFromRecordingTransitionsToPaused() {
        controller.start()

        controller.pause()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Paused("TEST_SOURCE", 123L))
        assertThat(engine.pauseCount).isEqualTo(1)
    }

    @Test
    fun pauseFromIdleIsIgnored() {
        controller.pause()

        assertThat(controller.state.value).isEqualTo(RecordingSessionState.Idle)
        assertThat(engine.pauseCount).isEqualTo(0)
    }

    @Test
    fun pauseWhilePausedIsIgnored() {
        controller.start()
        controller.pause()

        controller.pause()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Paused("TEST_SOURCE", 123L))
        assertThat(engine.pauseCount).isEqualTo(1)
    }

    @Test
    fun resumeFromPausedTransitionsToRecording() {
        controller.start()
        controller.pause()

        controller.resume()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Recording("TEST_SOURCE", 123L))
        assertThat(engine.resumeCount).isEqualTo(1)
    }

    @Test
    fun resumeFromIdleIsIgnored() {
        controller.resume()

        assertThat(controller.state.value).isEqualTo(RecordingSessionState.Idle)
        assertThat(engine.resumeCount).isEqualTo(0)
    }

    @Test
    fun resumeWithDeniedPermissionReportsPermissionRequired() {
        controller.start()
        controller.pause()
        permissionChecker.required = ClientErrorCode.MIC_PERMISSION_REQUIRED

        controller.resume()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.PermissionRequired(ClientErrorCode.MIC_PERMISSION_REQUIRED))
        assertThat(engine.resumeCount).isEqualTo(0)
    }

    @Test
    fun stopFromRecordingTransitionsToIdle() {
        controller.start()

        controller.stop()

        assertThat(controller.state.value).isEqualTo(RecordingSessionState.Idle)
        assertThat(engine.stopCount).isEqualTo(1)
    }

    @Test
    fun stopFromPausedTransitionsToIdle() {
        controller.start()
        controller.pause()

        controller.stop()

        assertThat(controller.state.value).isEqualTo(RecordingSessionState.Idle)
        assertThat(engine.stopCount).isEqualTo(1)
    }

    @Test
    fun stopFromIdleIsIgnored() {
        controller.stop()

        assertThat(controller.state.value).isEqualTo(RecordingSessionState.Idle)
        assertThat(engine.stopCount).isEqualTo(0)
    }

    @Test
    fun startWhileRecordingIsIdempotent() {
        controller.start()

        controller.start()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Recording("TEST_SOURCE", 123L))
        assertThat(engine.startCount).isEqualTo(1)
    }

    @Test
    fun startAfterFailedCanRetry() {
        engine.startResult = RecordingEngineResult.Failure(ClientErrorCode.RECORDER_INIT_FAILED, "init")
        controller.start()
        engine.startResult = RecordingEngineResult.Success("TEST_SOURCE")

        controller.start()

        assertThat(controller.state.value)
            .isEqualTo(RecordingSessionState.Recording("TEST_SOURCE", 123L))
        assertThat(engine.startCount).isEqualTo(2)
    }

    private class FakePermissionChecker : RecordingPermissionChecker {
        var required: ClientErrorCode? = null

        override fun requiredPermissionCode(): ClientErrorCode? = required
    }

    private class FakeEngine : RecordingEngine {
        var startResult: RecordingEngineResult = RecordingEngineResult.Success("TEST_SOURCE")
        var pauseResult: RecordingEngineResult = RecordingEngineResult.Success("TEST_SOURCE")
        var resumeResult: RecordingEngineResult = RecordingEngineResult.Success("TEST_SOURCE")
        var stopResult: RecordingEngineResult = RecordingEngineResult.Success("TEST_SOURCE")
        var startCount = 0
        var pauseCount = 0
        var resumeCount = 0
        var stopCount = 0

        override fun start(outputDirectory: File): RecordingEngineResult {
            startCount++
            return startResult
        }

        override fun pause(): RecordingEngineResult {
            pauseCount++
            return pauseResult
        }

        override fun resume(): RecordingEngineResult {
            resumeCount++
            return resumeResult
        }

        override fun stop(): RecordingEngineResult {
            stopCount++
            return stopResult
        }
    }
}
