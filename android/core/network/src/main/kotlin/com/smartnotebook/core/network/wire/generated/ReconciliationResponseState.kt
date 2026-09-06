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

@Serializable(with = ReconciliationResponseStateSerializer::class)
public enum class ReconciliationResponseState {
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

public object ReconciliationResponseStateSerializer : KSerializer<ReconciliationResponseState> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("ReconciliationResponseState", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: ReconciliationResponseState) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): ReconciliationResponseState {
        val raw = decoder.decodeString()
        return ReconciliationResponseState.entries.firstOrNull { it.wireValue == raw } ?: ReconciliationResponseState.UNKNOWN
    }
}

