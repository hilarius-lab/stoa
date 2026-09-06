package com.smartnotebook.core.model

import java.time.Instant
import java.util.UUID

public data class AudioAckInfo(
    val clientSessionId: UUID,
    val durableAck: Boolean,
    val chunk: AudioChunkInfo,
)

public data class AudioChunkInfo(
    val clientChunkId: String,
    val sequence: Long,
    val status: String,
    val byteLength: Long,
    val durationMs: Long,
    val mimeType: String,
    val contentHash: String,
    val codec: String?,
    val channels: Long?,
    val sampleRateHz: Long?,
    val retainPermanently: Boolean,
    val sourceStartMs: Long,
    val sourceEndMs: Long,
    val capturedAt: Instant?,
    val retainUntil: Instant?,
    val createdAt: Instant,
    val updatedAt: Instant,
)
