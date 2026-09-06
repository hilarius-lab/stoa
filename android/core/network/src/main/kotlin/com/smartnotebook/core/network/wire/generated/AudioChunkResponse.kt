// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class AudioChunkResponse(
    @SerialName("byte_length")
    val byteLength: Long,
    @Contextual
    @SerialName("captured_at")
    val capturedAt: Instant?,
    val channels: Long?,
    @SerialName("client_chunk_id")
    val clientChunkId: String,
    val codec: String?,
    @SerialName("content_hash")
    val contentHash: String,
    @Contextual
    @SerialName("created_at")
    val createdAt: Instant,
    @SerialName("duration_ms")
    val durationMs: Long,
    @SerialName("mime_type")
    val mimeType: String,
    @SerialName("retain_permanently")
    val retainPermanently: Boolean,
    @Contextual
    @SerialName("retain_until")
    val retainUntil: Instant?,
    @SerialName("sample_rate_hz")
    val sampleRateHz: Long?,
    val sequence: Long,
    @SerialName("source_end_ms")
    val sourceEndMs: Long,
    @SerialName("source_start_ms")
    val sourceStartMs: Long,
    val status: String,
    @Contextual
    @SerialName("updated_at")
    val updatedAt: Instant
)
