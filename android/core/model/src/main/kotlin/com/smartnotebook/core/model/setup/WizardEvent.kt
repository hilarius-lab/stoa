package com.smartnotebook.core.model.setup

public sealed interface WizardEvent {
    public data object WelcomeAccepted : WizardEvent

    public data object ServerAddressSubmitted : WizardEvent

    public data object ProbePassed : WizardEvent

    public data class ProbeFailed(
        val detail: String,
    ) : WizardEvent

    public data class ProbeBlocked(
        val detail: String,
    ) : WizardEvent

    public data object NotificationGranted : WizardEvent

    public data object NotificationDenied : WizardEvent

    public data object PushEnabled : WizardEvent

    public data object PushSkipped : WizardEvent

    public data object MicrophoneGranted : WizardEvent

    public data object MicrophoneDenied : WizardEvent

    public data object GoBack : WizardEvent

    public data object RetryStep : WizardEvent

    public data object Reset : WizardEvent
}
