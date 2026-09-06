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
public data class KnowledgeLibrary(
    val description: String,
    @Contextual
    val id: UUID,
    val key: String,
    @SerialName("local_action")
    val localAction: String,
    @SerialName("offline_enabled")
    val offlineEnabled: Boolean,
    @SerialName("privacy_class")
    val privacyClass: String,
    val scope: Map<String, JsonElement>,
    val stats: LibraryStats,
    @SerialName("sync_mode")
    val syncMode: String,
    val title: String,
    val type: String,
    @Contextual
    @SerialName("updated_at")
    val updatedAt: Instant,
    val version: Long
)
