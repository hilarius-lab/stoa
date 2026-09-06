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

@Serializable(with = KnowledgeChangeOperationSerializer::class)
public enum class KnowledgeChangeOperation {
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

public object KnowledgeChangeOperationSerializer : KSerializer<KnowledgeChangeOperation> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("KnowledgeChangeOperation", PrimitiveKind.STRING)

    override fun serialize(encoder: Encoder, value: KnowledgeChangeOperation) {
        encoder.encodeString(value.wireValue)
    }

    override fun deserialize(decoder: Decoder): KnowledgeChangeOperation {
        val raw = decoder.decodeString()
        return KnowledgeChangeOperation.entries.firstOrNull { it.wireValue == raw } ?: KnowledgeChangeOperation.UNKNOWN
    }
}

