package com.smartnotebook.core.model

public data class ServerProfile(
    val name: String,
    val scheme: String,
    val host: String,
    val port: Int,
    val basePath: String,
    val sseBasePath: String? = null,
    val requestTimeoutMillis: Long,
    val connectionTimeoutMillis: Long,
) {
    public val baseUrl: String
        get() = "$scheme://$host:$port$basePath"
}
