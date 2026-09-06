package com.smartnotebook.core.model

public enum class RetryClass {
    NEVER,
    IMMEDIATE,
    BACKOFF,
    NETWORK,
    USER_ACTION,
    UNKNOWN,
}
