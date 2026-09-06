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
public data class DashboardEntityResponse(
    val answer: String? = null,
    @SerialName("answer_source")
    val answerSource: String? = null,
    val confidence: Double? = null,
    val content: String? = null,
    @Contextual
    @SerialName("created_at")
    val createdAt: Instant,
    val description: String? = null,
    @Contextual
    val id: UUID,
    val priority: Double? = null,
    val question: String? = null,
    @SerialName("question_kind")
    val questionKind: String? = null,
    val status: String,
    val title: String? = null,
    val type: String,
    @Contextual
    @SerialName("updated_at")
    val updatedAt: Instant
)
