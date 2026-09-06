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

@Serializable(with = ErrorResponseRetryClassSerializer::class)
public enum class ErrorResponseRetryClass {
    NEVER,
    IMMEDIATE,
    BACKOFF,
    NETWORK,
    USER_ACTION,
    UNKNOWN;

    public val wireValue: String
        get() = when (this) {
            NEVER -> "never"
            IMMEDIATE -> "immediate"
            BACKOFF -> "backoff"
            NETWORK -> "network"
            USER_ACTION -> "user_action"
            UNKNOWN -> "unknown"
        }
}

public object ErrorResponseRetryClassSerializer : KSerializer<ErrorResponseRetryClass> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("ErrorResponseRetryClass", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: ErrorResponseRetryClass) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): ErrorResponseRetryClass {
        val raw = decoder.decodeString()
        return ErrorResponseRetryClass.entries.firstOrNull { it.wireValue == raw } ?: ErrorResponseRetryClass.UNKNOWN
    }
}

