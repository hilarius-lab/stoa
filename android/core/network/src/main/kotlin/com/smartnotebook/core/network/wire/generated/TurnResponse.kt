// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class TurnResponse(
    @Contextual
    @SerialName("assistant_message_id")
    val assistantMessageId: UUID?,
    val attempts: Long,
    @Contextual
    @SerialName("client_turn_id")
    val clientTurnId: UUID,
    @Contextual
    @SerialName("completed_at")
    val completedAt: Instant?,
    @Contextual
    @SerialName("conversation_id")
    val conversationId: UUID,
    @Contextual
    @SerialName("created_at")
    val createdAt: Instant,
    val error: String?,
    @Contextual
    val id: UUID,
    @Contextual
    @SerialName("started_at")
    val startedAt: Instant?,
    val status: String,
    @Contextual
    @SerialName("updated_at")
    val updatedAt: Instant,
    @Contextual
    @SerialName("user_message_id")
    val userMessageId: UUID
)
