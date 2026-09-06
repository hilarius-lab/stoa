package com.smartnotebook.core.model

import java.time.Instant

public data class ClientError(
    val code: ClientErrorCode,
    val retryClass: RetryClass,
    val message: String,
    val httpStatus: Int? = null,
    val rawCode: String? = null,
    val requestId: String? = null,
    val timestamp: Instant? = null,
    val details: Map<String, Any?>? = null,
    val retryAfterSeconds: Long? = null,
)
