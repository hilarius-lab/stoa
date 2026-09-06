// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class AudioProfile(
    @SerialName("bitrate_bps")
    val bitrateBps: Long?,
    val channels: Long?,
    val codec: String,
    val container: String,
    val id: String,
    @SerialName("max_chunk_bytes")
    val maxChunkBytes: Long,
    @SerialName("mime_type")
    val mimeType: String,
    @SerialName("sample_rate_hz")
    val sampleRateHz: Long?,
    @SerialName("target_segment_ms")
    val targetSegmentMs: Long
)
