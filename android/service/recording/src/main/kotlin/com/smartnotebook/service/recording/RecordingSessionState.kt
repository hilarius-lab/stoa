package com.smartnotebook.service.recording

import com.smartnotebook.core.model.ClientErrorCode

public sealed interface RecordingSessionState {
    public data object Idle : RecordingSessionState

    public data object Preparing : RecordingSessionState

    public data class Recording(
        public val sourceName: String,
        public val startedAtMs: Long,
    ) : RecordingSessionState

    public data class Paused(
        public val sourceName: String,
        public val pausedAtMs: Long,
    ) : RecordingSessionState

    public data object Stopping : RecordingSessionState

    public data class PermissionRequired(
        public val code: ClientErrorCode,
    ) : RecordingSessionState

    public data class Failed(
        public val code: ClientErrorCode,
        public val detail: String,
    ) : RecordingSessionState
}
