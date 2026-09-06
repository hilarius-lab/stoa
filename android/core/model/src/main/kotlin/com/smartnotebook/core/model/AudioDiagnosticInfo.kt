package com.smartnotebook.core.model

public data class AudioDiagnosticInfo(
    val compatible: Boolean,
    val profileId: String?,
    val declaredMimeType: String,
    val detectedContainer: String?,
    val detectedCodec: String?,
    val sampleRateHz: Long?,
    val channels: Long?,
    val bitrateBps: Long?,
    val durationMs: Long?,
    val byteLength: Long,
    val reasonCodes: List<String>,
    val durableStateCreated: Boolean,
)
