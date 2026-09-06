package com.smartnotebook.core.model

import java.time.Instant
import java.util.UUID

public data class ChatTurn(
    val id: UUID,
    val conversationId: UUID,
    val clientTurnId: UUID,
    val userMessageId: UUID,
    val assistantMessageId: UUID?,
    val status: String,
    val error: String?,
    val attempts: Long,
    val createdAt: Instant,
    val startedAt: Instant?,
    val completedAt: Instant?,
    val updatedAt: Instant,
)
