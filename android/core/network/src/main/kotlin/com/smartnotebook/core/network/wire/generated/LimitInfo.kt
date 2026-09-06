// GENERATED - DO NOT EDIT
// Source: contracts/client-openapi-v1.json (sha256:c76a00001c83cbac5a153f754f31b673166713d8cd93d950873a6831594767ac)
// Generator: wiregen v1 (contract v1)

package com.smartnotebook.core.network.wire.generated
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
public data class LimitInfo(
    @SerialName("dashboard_cache_max_age_seconds")
    val dashboardCacheMaxAgeSeconds: Long,
    @SerialName("dashboard_cards_per_section")
    val dashboardCardsPerSection: Long,
    @SerialName("dashboard_detail_max_chars")
    val dashboardDetailMaxChars: Long,
    @SerialName("dashboard_history_hours")
    val dashboardHistoryHours: Long,
    @SerialName("dashboard_preview_max_chars")
    val dashboardPreviewMaxChars: Long,
    @SerialName("dashboard_title_max_chars")
    val dashboardTitleMaxChars: Long,
    @SerialName("live_transcript_max_segments")
    val liveTranscriptMaxSegments: Long,
    @SerialName("live_transcript_window_seconds")
    val liveTranscriptWindowSeconds: Long,
    @SerialName("request_timeout_seconds")
    val requestTimeoutSeconds: Long,
    @SerialName("server_ephemeral_chat_retention_hours")
    val serverEphemeralChatRetentionHours: Long,
    @SerialName("server_raw_audio_retention_days")
    val serverRawAudioRetentionDays: Long,
    @SerialName("server_technical_log_retention_hours")
    val serverTechnicalLogRetentionHours: Long
)
