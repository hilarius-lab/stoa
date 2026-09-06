package com.smartnotebook.core.network.wire

import kotlinx.serialization.KSerializer
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.modules.SerializersModule
import java.time.Instant
import java.util.UUID

public const val WIRE_CONTRACT_VERSION: String = "1"

public object UuidSerializer : KSerializer<UUID> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("com.smartnotebook.core.network.wire.Uuid", PrimitiveKind.STRING)

    override fun serialize(
        encoder: Encoder,
        value: UUID,
    ) {
        encoder.encodeString(value.toString())
    }

    override fun deserialize(decoder: Decoder): UUID = UUID.fromString(decoder.decodeString())
}

public object InstantSerializer : KSerializer<Instant> {
    override val descriptor: SerialDescriptor =
        PrimitiveSerialDescriptor("com.smartnotebook.core.network.wire.InstantIso8601", PrimitiveKind.STRING)

    override fun serialize(
        encoder: Encoder,
        value: Instant,
    ) {
        encoder.encodeString(value.toString())
    }

    override fun deserialize(decoder: Decoder): Instant = Instant.parse(decoder.decodeString())
}

public val WireSerializersModule: SerializersModule =
    SerializersModule {
        contextual(UUID::class, UuidSerializer)
        contextual(Instant::class, InstantSerializer)
    }

public val WireJson: Json =
    Json {
        serializersModule = WireSerializersModule
        ignoreUnknownKeys = true
        encodeDefaults = true
        isLenient = false
        explicitNulls = true
    }
