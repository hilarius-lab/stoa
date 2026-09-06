package com.smartnotebook.core.model

public data class ClientPreferences(
    val language: String = DEFAULT_LANGUAGE,
    val audioQualityProfile: String = DEFAULT_AUDIO_QUALITY_PROFILE,
    val segmentDurationMillis: Long = DEFAULT_SEGMENT_DURATION_MILLIS,
    val deviceName: String? = null,
) {
    public companion object {
        public const val DEFAULT_LANGUAGE: String = "de"
        public const val DEFAULT_AUDIO_QUALITY_PROFILE: String = "android_aac_lc_v1"
        public const val DEFAULT_SEGMENT_DURATION_MILLIS: Long = 10_000L
    }
}
