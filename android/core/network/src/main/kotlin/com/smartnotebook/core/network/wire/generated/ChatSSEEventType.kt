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

@Serializable(with = ChatSSEEventTypeSerializer::class)
public enum class ChatSSEEventType {
    STARTED,
    DELTA,
    CITATION,
    ACTION,
    COMPLETED,
    FAILED,
    ABORTED,
    UNKNOWN;

    public val wireValue: String
        get() = when (this) {
            STARTED -> "started"
            DELTA -> "delta"
            CITATION -> "citation"
            ACTION -> "action"
            COMPLETED -> "completed"
            FAILED -> "failed"
            ABORTED -> "aborted"
            UNKNOWN -> "unknown"
        }
}

public object ChatSSEEventTypeSerializer : KSerializer<ChatSSEEventType> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("ChatSSEEventType", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: ChatSSEEventType) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): ChatSSEEventType {
        val raw = decoder.decodeString()
        return ChatSSEEventType.entries.firstOrNull { it.wireValue == raw } ?: ChatSSEEventType.UNKNOWN
    }
}

