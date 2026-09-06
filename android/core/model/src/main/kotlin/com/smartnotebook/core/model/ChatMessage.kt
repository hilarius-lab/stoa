package com.smartnotebook.core.model

import java.time.Instant
import java.util.UUID

public data class ChatMessage(
    val id: UUID,
    val sequence: Long,
    val role: String,
    val content: String,
    val contentFormat: String,
    val createdAt: Instant,
)
