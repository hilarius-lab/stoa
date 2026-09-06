package com.smartnotebook.core.model

import java.time.Instant

public data class WireErrorInfo(
    val code: String,
    val message: String,
    val requestId: String,
    val retryClass: RetryClass,
    val timestamp: Instant,
    val details: Map<String, Any?>?,
)
