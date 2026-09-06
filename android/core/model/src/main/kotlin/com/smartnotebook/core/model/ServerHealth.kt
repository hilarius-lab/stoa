package com.smartnotebook.core.model

import java.time.Instant

public data class ServerHealth(
    val contractVersion: String,
    val serverVersion: String,
    val status: String,
    val time: Instant,
)
