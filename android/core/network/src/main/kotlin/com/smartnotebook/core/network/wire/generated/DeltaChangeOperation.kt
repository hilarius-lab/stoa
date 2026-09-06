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

@Serializable(with = DeltaChangeOperationSerializer::class)
public enum class DeltaChangeOperation {
    UPSERT,
    DELETE,
    REDIRECT,
    UNKNOWN;

    public val wireValue: String
        get() = when (this) {
            UPSERT -> "upsert"
            DELETE -> "delete"
            REDIRECT -> "redirect"
            UNKNOWN -> "unknown"
        }
}

public object DeltaChangeOperationSerializer : KSerializer<DeltaChangeOperation> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("DeltaChangeOperation", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: DeltaChangeOperation) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): DeltaChangeOperation {
        val raw = decoder.decodeString()
        return DeltaChangeOperation.entries.firstOrNull { it.wireValue == raw } ?: DeltaChangeOperation.UNKNOWN
    }
}

