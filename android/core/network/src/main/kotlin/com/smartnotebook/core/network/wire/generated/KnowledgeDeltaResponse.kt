// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class KnowledgeDeltaResponse(
    val changes: List<DeltaChange>,
    @SerialName("has_more")
    val hasMore: Boolean,
    val mode: String,
    @SerialName("next_cursor")
    val nextCursor: String
)
