// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.KSerializer
import kotlinx.serialization.Serializable
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder

@Serializable(with = SessionSummaryStateSerializer::class)
public enum class SessionSummaryState {
    CREATED,
    RECORDING,
    PAUSED,
    DRAINING,
    PROCESSING,
    COMPLETED,
    FAILED,
    ATTENTION_REQUIRED,
    ABORTED,
    UNKNOWN;

    public val wireValue: String
        get() = when (this) {
            CREATED -> "created"
            RECORDING -> "recording"
            PAUSED -> "paused"
            DRAINING -> "draining"
            PROCESSING -> "processing"
            COMPLETED -> "completed"
            FAILED -> "failed"
            ATTENTION_REQUIRED -> "attention_required"
            ABORTED -> "aborted"
            UNKNOWN -> "unknown"
        }
}

public object SessionSummaryStateSerializer : KSerializer<SessionSummaryState> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("SessionSummaryState", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: SessionSummaryState) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): SessionSummaryState {
        val raw = decoder.decodeString()
        return SessionSummaryState.entries.firstOrNull { it.wireValue == raw } ?: SessionSummaryState.UNKNOWN
    }
}

