package com.smartnotebook.service.recording

import kotlinx.coroutines.flow.StateFlow

public interface RecordingControl {
    public val state: StateFlow<RecordingSessionState>

    public fun start()

    public fun pause()

    public fun resume()

    public fun stop()
}
