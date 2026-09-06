// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
public data class DashboardComponent(
    val action: DashboardAction? = null,
    @SerialName("border_role")
    val borderRole: String? = null,
    @SerialName("color_role")
    val colorRole: String? = null,
    val component: String,
    @SerialName("default_mode")
    val defaultMode: String? = null,
    @SerialName("entity_ref")
    val entityRef: EntityRef? = null,
    @SerialName("entity_type")
    val entityType: String? = null,
    val format: String? = null,
    val icon: String? = null,
    val id: String? = null,
    val items: List<DashboardComponent>? = null,
    val layout: Map<String, JsonElement>? = null,
    val modes: List<String>? = null,
    @SerialName("preferred_span")
    val preferredSpan: String? = null,
    val preview: String? = null,
    val priority: Double? = null,
    val rank: Long? = null,
    @SerialName("reason_code")
    val reasonCode: String? = null,
    @SerialName("reason_text")
    val reasonText: String? = null,
    val required: Boolean,
    val severity: String? = null,
    @SerialName("source_end_ms")
    val sourceEndMs: Long? = null,
    @SerialName("source_start_ms")
    val sourceStartMs: Long? = null,
    @SerialName("spacing_role")
    val spacingRole: String? = null,
    val status: String? = null,
    val text: String? = null,
    val title: String? = null
)
