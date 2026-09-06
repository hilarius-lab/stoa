// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
public data class TextCaptureCreate(
    @Contextual
    @SerialName("client_capture_id")
    val clientCaptureId: UUID,
    val content: String,
    @SerialName("context_ref")
    val contextRef: Map<String, JsonElement>? = null,
    val mode: String? = null
)
