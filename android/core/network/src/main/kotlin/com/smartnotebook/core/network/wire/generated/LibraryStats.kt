// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class LibraryStats(
    @SerialName("change_log_bytes")
    val changeLogBytes: Long,
    @SerialName("entity_count")
    val entityCount: Long,
    @SerialName("latest_change_sequence")
    val latestChangeSequence: Long
)
