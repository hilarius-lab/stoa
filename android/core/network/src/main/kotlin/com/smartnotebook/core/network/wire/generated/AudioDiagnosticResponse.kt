// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class AudioDiagnosticResponse(
    @SerialName("bitrate_bps")
    val bitrateBps: Long?,
    @SerialName("byte_length")
    val byteLength: Long,
    val channels: Long?,
    val compatible: Boolean,
    @SerialName("declared_mime_type")
    val declaredMimeType: String,
    @SerialName("detected_codec")
    val detectedCodec: String?,
    @SerialName("detected_container")
    val detectedContainer: String?,
    @SerialName("durable_state_created")
    val durableStateCreated: Boolean,
    @SerialName("duration_ms")
    val durationMs: Long?,
    @SerialName("profile_id")
    val profileId: String?,
    @SerialName("reason_codes")
    val reasonCodes: List<String>,
    @SerialName("sample_rate_hz")
    val sampleRateHz: Long?
)
