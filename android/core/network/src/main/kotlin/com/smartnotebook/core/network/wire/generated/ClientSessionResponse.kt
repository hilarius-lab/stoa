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
public data class ClientSessionResponse(
    @Contextual
    @SerialName("aborted_at")
    val abortedAt: Instant?,
    @SerialName("capture_mode")
    val captureMode: String,
    @SerialName("capture_result")
    val captureResult: Map<String, JsonElement>?,
    @Contextual
    @SerialName("client_session_id")
    val clientSessionId: UUID,
    @SerialName("context_ref")
    val contextRef: Map<String, JsonElement>?,
    @Contextual
    @SerialName("created_at")
    val createdAt: Instant,
    @SerialName("device_metadata")
    val deviceMetadata: Map<String, JsonElement>,
    @SerialName("expected_final_sequence")
    val expectedFinalSequence: Long?,
    @SerialName("final_source_end_ms")
    val finalSourceEndMs: Long?,
    @Contextual
    @SerialName("finalized_at")
    val finalizedAt: Instant?,
    @Contextual
    @SerialName("finish_requested_at")
    val finishRequestedAt: Instant?,
    @SerialName("last_error")
    val lastError: String?,
    @Contextual
    @SerialName("paused_at")
    val pausedAt: Instant?,
    val state: ClientSessionResponseState,
    @Contextual
    @SerialName("updated_at")
    val updatedAt: Instant
)
