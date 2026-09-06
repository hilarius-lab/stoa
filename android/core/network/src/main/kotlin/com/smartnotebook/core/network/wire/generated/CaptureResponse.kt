// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
public data class CaptureResponse(
    val content: String,
    @SerialName("context_ref")
    val contextRef: Map<String, JsonElement>?,
    @Contextual
    @SerialName("conversation_id")
    val conversationId: UUID?,
    @Contextual
    @SerialName("created_at")
    val createdAt: Instant,
    val error: String?,
    @SerialName("event_id")
    val eventId: Long?,
    @Contextual
    val id: UUID,
    val mode: String,
    @SerialName("resolved_intent")
    val resolvedIntent: String,
    val result: Map<String, JsonElement>?,
    val status: String,
    @Contextual
    @SerialName("turn_id")
    val turnId: UUID?,
    @Contextual
    @SerialName("updated_at")
    val updatedAt: Instant
)
