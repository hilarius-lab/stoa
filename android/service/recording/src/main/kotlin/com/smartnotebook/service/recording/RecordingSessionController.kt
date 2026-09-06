package com.smartnotebook.service.recording

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.util.concurrent.atomic.AtomicReference

public class RecordingSessionController(
    private val permissionChecker: RecordingPermissionChecker,
    private val engine: RecordingEngine,
    private val clock: () -> Long,
    private val outputDirectoryProvider: () -> File,
) : RecordingControl {
    private val lock = Any()
    private val activeOperation = AtomicReference<Operation?>(null)
    private val mutableState = MutableStateFlow<RecordingSessionState>(RecordingSessionState.Idle)

    override val state: StateFlow<RecordingSessionState> = mutableState.asStateFlow()

    override fun start() {
        synchronized(lock) {
            if (isBusy() || isStartBlocked()) {
                return
            }

            markBusy(Operation.START)
            val denied = permissionChecker.requiredPermissionCode()
            if (denied != null) {
                setState(RecordingSessionState.PermissionRequired(denied))
                clearBusy()
                return
            }

            setState(RecordingSessionState.Preparing)
            when (val result = engine.start(outputDirectoryProvider())) {
                is RecordingEngineResult.Success ->
                    setState(RecordingSessionState.Recording(result.sourceName, clock()))
                is RecordingEngineResult.Failure ->
                    setState(RecordingSessionState.Failed(result.code, result.detail))
            }
            clearBusy()
        }
    }

    override fun pause() {
        synchronized(lock) {
            if (isBusy() || state.value !is RecordingSessionState.Recording) {
                return
            }

            markBusy(Operation.PAUSE)
            when (val result = engine.pause()) {
                is RecordingEngineResult.Success ->
                    setState(RecordingSessionState.Paused(result.sourceName, clock()))
                is RecordingEngineResult.Failure ->
                    setState(RecordingSessionState.Failed(result.code, result.detail))
            }
            clearBusy()
        }
    }

    override fun resume() {
        synchronized(lock) {
            if (isBusy() || state.value !is RecordingSessionState.Paused) {
                return
            }

            markBusy(Operation.RESUME)
            setState(RecordingSessionState.Preparing)
            val denied = permissionChecker.requiredPermissionCode()
            if (denied != null) {
                setState(RecordingSessionState.PermissionRequired(denied))
                clearBusy()
                return
            }

            when (val result = engine.resume()) {
                is RecordingEngineResult.Success ->
                    setState(RecordingSessionState.Recording(result.sourceName, clock()))
                is RecordingEngineResult.Failure ->
                    setState(RecordingSessionState.Failed(result.code, result.detail))
            }
            clearBusy()
        }
    }

    override fun stop() {
        synchronized(lock) {
            if (isBusy() || !isStopAllowed()) {
                return
            }

            markBusy(Operation.STOP)
            setState(RecordingSessionState.Stopping)
            when (val result = engine.stop()) {
                is RecordingEngineResult.Success ->
                    setState(RecordingSessionState.Idle)
                is RecordingEngineResult.Failure ->
                    setState(RecordingSessionState.Failed(result.code, result.detail))
            }
            clearBusy()
        }
    }

    private fun isBusy(): Boolean = activeOperation.get() != null

    private fun isStartBlocked(): Boolean =
        state.value is RecordingSessionState.Preparing ||
            state.value is RecordingSessionState.Recording ||
            state.value is RecordingSessionState.Stopping

    private fun isStopAllowed(): Boolean =
        state.value is RecordingSessionState.Recording ||
            state.value is RecordingSessionState.Paused

    private fun markBusy(operation: Operation) {
        activeOperation.set(operation)
    }

    private fun clearBusy() {
        activeOperation.set(null)
    }

    private fun setState(value: RecordingSessionState) {
        mutableState.value = value
    }

    private enum class Operation {
        START,
        PAUSE,
        RESUME,
        STOP,
    }
}
