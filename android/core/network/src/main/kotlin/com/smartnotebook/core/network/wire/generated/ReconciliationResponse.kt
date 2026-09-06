// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.util.UUID
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class ReconciliationResponse(
    val chunks: List<ReconciliationChunk>,
    @Contextual
    @SerialName("client_session_id")
    val clientSessionId: UUID,
    val conflicts: List<UploadConflict>,
    @SerialName("expected_final_sequence")
    val expectedFinalSequence: Long?,
    @SerialName("missing_sequences")
    val missingSequences: List<Long>,
    @SerialName("received_sequences")
    val receivedSequences: List<Long>,
    val state: ReconciliationResponseState,
    @SerialName("upload_complete")
    val uploadComplete: Boolean
)
