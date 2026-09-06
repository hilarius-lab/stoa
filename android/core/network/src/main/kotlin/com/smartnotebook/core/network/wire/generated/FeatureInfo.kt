// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class FeatureInfo(
    @SerialName("audio_upload")
    val audioUpload: Boolean,
    @SerialName("audio_upload_diagnostics")
    val audioUploadDiagnostics: Boolean,
    val chat: Boolean,
    @SerialName("dashboard_snapshot")
    val dashboardSnapshot: Boolean,
    @SerialName("dashboard_sse")
    val dashboardSse: Boolean,
    @SerialName("offline_knowledge_sync")
    val offlineKnowledgeSync: Boolean,
    @SerialName("session_recovery")
    val sessionRecovery: Boolean,
    @SerialName("unified_push")
    val unifiedPush: Boolean
)
