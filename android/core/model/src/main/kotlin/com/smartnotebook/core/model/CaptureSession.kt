package com.smartnotebook.core.model

import java.time.Instant
import java.util.UUID

public data class CaptureSession(
    val id: UUID,
    val state: SessionState,
    val captureMode: CaptureMode,
    val createdAt: Instant,
    val updatedAt: Instant,
    val finalizedAt: Instant?,
    val finishRequestedAt: Instant?,
    val pausedAt: Instant?,
    val abortedAt: Instant?,
    val expectedFinalSequence: Long?,
    val finalSourceEndMs: Long?,
    val lastError: String?,
    val contextRef: Map<String, Any?>?,
    val captureResult: Map<String, Any?>?,
    val deviceMetadata: Map<String, Any?>,
)
