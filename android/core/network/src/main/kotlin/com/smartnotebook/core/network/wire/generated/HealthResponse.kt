// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class HealthResponse(
    @SerialName("contract_version")
    val contractVersion: String,
    @SerialName("server_version")
    val serverVersion: String,
    val status: String,
    @Contextual
    val time: Instant
)
