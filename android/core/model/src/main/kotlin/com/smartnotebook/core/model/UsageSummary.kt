package com.smartnotebook.core.model

import java.util.UUID

public data class UsageSummary(
    val acceptedCount: Long,
    val batchId: UUID,
    val idempotent: Boolean,
)
