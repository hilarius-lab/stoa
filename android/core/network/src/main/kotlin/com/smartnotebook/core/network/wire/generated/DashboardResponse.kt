// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import java.time.Instant
import kotlinx.serialization.Contextual
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class DashboardResponse(
    @Contextual
    @SerialName("generated_at")
    val generatedAt: Instant,
    val mode: DashboardResponseMode,
    @SerialName("primary_live_session")
    val primaryLiveSession: SessionSummary?,
    val processing: ProcessingSummary? = null,
    val revision: Long,
    @SerialName("schema_version")
    val schemaVersion: String,
    val scope: String,
    val sections: List<DashboardComponent>,
    @Contextual
    @SerialName("server_time")
    val serverTime: Instant,
    val sessions: List<SessionSummary>
)
