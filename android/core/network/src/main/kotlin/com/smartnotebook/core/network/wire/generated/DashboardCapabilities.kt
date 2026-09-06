// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class DashboardCapabilities(
    val actions: List<String>,
    @SerialName("border_roles")
    val borderRoles: List<String>,
    @SerialName("color_roles")
    val colorRoles: List<String>,
    @SerialName("component_types")
    val componentTypes: List<String>,
    @SerialName("icon_tokens")
    val iconTokens: List<String>,
    @SerialName("preferred_spans")
    val preferredSpans: List<String>,
    @SerialName("schema_version")
    val schemaVersion: String,
    @SerialName("spacing_roles")
    val spacingRoles: List<String>,
    @SerialName("unknown_optional_component")
    val unknownOptionalComponent: String,
    @SerialName("unknown_required_component")
    val unknownRequiredComponent: String
)
