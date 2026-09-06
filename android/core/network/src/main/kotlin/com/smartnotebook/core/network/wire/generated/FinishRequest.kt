// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class FinishRequest(
    @SerialName("final_sequence")
    val finalSequence: Long,
    @SerialName("final_source_end_ms")
    val finalSourceEndMs: Long? = null
)
