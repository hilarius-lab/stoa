package com.smartnotebook.service.recording

import com.smartnotebook.core.model.ClientErrorCode
import java.io.File

public sealed interface RecordingEngineResult {
    public data class Success(
        public val sourceName: String,
    ) : RecordingEngineResult

    public data class Failure(
        public val code: ClientErrorCode,
        public val detail: String,
    ) : RecordingEngineResult
}

public interface RecordingEngine {
    public fun start(outputDirectory: File): RecordingEngineResult

    public fun pause(): RecordingEngineResult

    public fun resume(): RecordingEngineResult

    public fun stop(): RecordingEngineResult
}
