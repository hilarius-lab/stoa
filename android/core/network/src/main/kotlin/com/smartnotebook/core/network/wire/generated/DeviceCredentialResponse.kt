// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class DeviceCredentialResponse(
    @Contextual
    @SerialName("client_installation_id")
    val clientInstallationId: UUID,
    val credential: String,
    @Contextual
    @SerialName("expires_at")
    val expiresAt: Instant,
    @Contextual
    @SerialName("rotate_after")
    val rotateAfter: Instant
)
