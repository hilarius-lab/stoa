package com.smartnotebook.core.model.setup

public enum class WizardStep {
    WELCOME,
    SERVER,
    TLS,
    CAPABILITIES,
    COMPATIBILITY,
    INSTALLATION,
    NOTIFICATION,
    PUSH_OPTIONAL,
    MICROPHONE,
    AUDIO_TEST,
    UPLOAD_ACK_TEST,
    INITIAL_SYNC,
    COMPLETED,
    ;

    public val isProbeStep: Boolean
        get() =
            when (this) {
                TLS, CAPABILITIES, COMPATIBILITY, INSTALLATION, AUDIO_TEST, UPLOAD_ACK_TEST, INITIAL_SYNC -> true
                WELCOME, SERVER, NOTIFICATION, PUSH_OPTIONAL, MICROPHONE, COMPLETED -> false
            }

    public val next: WizardStep?
        get() = entries.getOrNull(ordinal + 1)

    public val previous: WizardStep?
        get() = entries.getOrNull(ordinal - 1)

    public companion object {
        public fun fromName(name: String?): WizardStep? = entries.firstOrNull { it.name == name }
    }
}
