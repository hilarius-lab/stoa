package com.smartnotebook.core.model

import java.time.Instant
import java.util.UUID

public data class Conversation(
    val id: UUID,
    val agent: AgentInfo,
    val status: String,
    val title: String,
    val revision: Long,
    val createdAt: Instant,
    val dashboardUntil: Instant,
    val lastActivityAt: Instant,
)
