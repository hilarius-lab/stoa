package com.smartnotebook.core.model

import java.time.Instant
import java.util.UUID

public data class ReconciliationResult(
    val clientSessionId: UUID,
    val state: SessionState,
    val uploadComplete: Boolean,
    val expectedFinalSequence: Long?,
    val missingSequences: List<Long>,
    val receivedSequences: List<Long>,
    val chunks: List<ReconciliationChunkInfo>,
    val conflicts: List<UploadConflictInfo>,
)

public data class ReconciliationChunkInfo(
    val sequence: Long,
    val clientChunkId: String,
    val contentHash: String,
    val byteLength: Long,
    val durableAck: Boolean,
    val status: String,
    val sourceStartMs: Long,
    val sourceEndMs: Long,
)

public data class UploadConflictInfo(
    val code: String,
    val occurredAt: Instant,
    val clientChunkId: String?,
    val sequence: Long?,
    val expected: Map<String, Any?>,
    val received: Map<String, Any?>,
)
