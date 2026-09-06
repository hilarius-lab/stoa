// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class Body_upload_v1_audio_api_client_v1_sessions__client_session_id__audio_chunks_post(
    val audio: String,
    @Contextual
    @SerialName("captured_at")
    val capturedAt: Instant? = null,
    val channels: Long? = null,
    @SerialName("client_chunk_id")
    val clientChunkId: String,
    val codec: String? = null,
    @SerialName("content_hash")
    val contentHash: String? = null,
    @SerialName("duration_ms")
    val durationMs: Long,
    @SerialName("sample_rate_hz")
    val sampleRateHz: Long? = null,
    val sequence: Long,
    @SerialName("source_end_ms")
    val sourceEndMs: Long,
    @SerialName("source_start_ms")
    val sourceStartMs: Long
)
