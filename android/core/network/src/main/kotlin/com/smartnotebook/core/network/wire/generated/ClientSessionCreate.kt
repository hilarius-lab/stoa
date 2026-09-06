// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
public data class ClientSessionCreate(
    @SerialName("capture_mode")
    val captureMode: String? = null,
    @Contextual
    @SerialName("client_session_id")
    val clientSessionId: UUID,
    @SerialName("context_ref")
    val contextRef: Map<String, JsonElement>? = null,
    @SerialName("device_metadata")
    val deviceMetadata: Map<String, JsonElement>? = null,
    val source: String? = null,
    @SerialName("source_type")
    val sourceType: String? = null,
    @Contextual
    @SerialName("started_at")
    val startedAt: Instant? = null,
    val title: String? = null
)
