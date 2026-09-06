// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class TransportCapabilities(
    @SerialName("background_refresh")
    val backgroundRefresh: String,
    @SerialName("fallback_refresh")
    val fallbackRefresh: String,
    @SerialName("foreground_refresh")
    val foregroundRefresh: String,
    val rest: Boolean,
    val sse: Boolean,
    @SerialName("sse_proxy_buffering")
    val sseProxyBuffering: Boolean,
    @SerialName("unified_push")
    val unifiedPush: Boolean
)
