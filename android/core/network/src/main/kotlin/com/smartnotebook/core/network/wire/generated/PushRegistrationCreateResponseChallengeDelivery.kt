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

@Serializable(with = PushRegistrationCreateResponseChallengeDeliverySerializer::class)
public enum class PushRegistrationCreateResponseChallengeDelivery {
    DELIVERED,
    FAILED,
    UNKNOWN;

    public val wireValue: String
        get() = when (this) {
            DELIVERED -> "delivered"
            FAILED -> "failed"
            UNKNOWN -> "unknown"
        }
}

public object PushRegistrationCreateResponseChallengeDeliverySerializer : KSerializer<PushRegistrationCreateResponseChallengeDelivery> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("PushRegistrationCreateResponseChallengeDelivery", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: PushRegistrationCreateResponseChallengeDelivery) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): PushRegistrationCreateResponseChallengeDelivery {
        val raw = decoder.decodeString()
        return PushRegistrationCreateResponseChallengeDelivery.entries.firstOrNull { it.wireValue == raw } ?: PushRegistrationCreateResponseChallengeDelivery.UNKNOWN
    }
}

