// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class PushRegistrationCreate(
    @Contextual
    @SerialName("client_installation_id")
    val clientInstallationId: UUID,
    @SerialName("client_public_key")
    val clientPublicKey: String,
    val distributor: String? = null,
    val endpoint: String,
    @Contextual
    @SerialName("registration_id")
    val registrationId: UUID
)
