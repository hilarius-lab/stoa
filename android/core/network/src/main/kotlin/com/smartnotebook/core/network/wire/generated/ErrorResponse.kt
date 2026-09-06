// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
public data class ErrorResponse(
    val code: String,
    val details: Map<String, JsonElement>? = null,
    val message: String,
    @SerialName("request_id")
    val requestId: String,
    @SerialName("retry_class")
    val retryClass: ErrorResponseRetryClass,
    @Contextual
    val timestamp: Instant
)
