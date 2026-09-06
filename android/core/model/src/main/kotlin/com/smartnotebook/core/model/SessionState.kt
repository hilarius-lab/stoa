package com.smartnotebook.core.model

public enum class SessionState {
    CREATED,
    RECORDING,
    PAUSED,
    DRAINING,
    PROCESSING,
    COMPLETED,
    FAILED,
    ATTENTION_REQUIRED,
    ABORTED,
    UNKNOWN,
}
