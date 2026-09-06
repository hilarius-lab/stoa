// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class CapabilitiesResponse(
    @SerialName("audio_profiles")
    val audioProfiles: List<AudioProfile>,
    @SerialName("completion_states")
    val completionStates: List<String>,
    val contract: ContractInfo,
    val dashboard: DashboardCapabilities,
    val features: FeatureInfo,
    val limits: LimitInfo,
    val server: ServerInfo,
    @SerialName("session_states")
    val sessionStates: List<String>,
    val status: String,
    @SerialName("status_message")
    val statusMessage: String?,
    val transports: TransportCapabilities
)
