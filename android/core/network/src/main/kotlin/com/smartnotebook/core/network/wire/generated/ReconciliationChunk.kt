// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class ReconciliationChunk(
    @SerialName("byte_length")
    val byteLength: Long,
    @SerialName("client_chunk_id")
    val clientChunkId: String,
    @SerialName("content_hash")
    val contentHash: String,
    @SerialName("durable_ack")
    val durableAck: Boolean,
    val sequence: Long,
    @SerialName("source_end_ms")
    val sourceEndMs: Long,
    @SerialName("source_start_ms")
    val sourceStartMs: Long,
    val status: String
)
