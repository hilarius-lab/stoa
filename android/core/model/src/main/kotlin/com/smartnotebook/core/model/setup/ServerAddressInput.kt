package com.smartnotebook.core.model.setup

public data class ServerAddressInput(
    val scheme: String,
    val host: String,
    val port: String,
    val basePath: String,
)
