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
public data class UploadConflict(
    @SerialName("client_chunk_id")
    val clientChunkId: String?,
    val code: String,
    val expected: Map<String, JsonElement>,
    @Contextual
    @SerialName("occurred_at")
    val occurredAt: Instant,
    val received: Map<String, JsonElement>,
    val sequence: Long?
)
