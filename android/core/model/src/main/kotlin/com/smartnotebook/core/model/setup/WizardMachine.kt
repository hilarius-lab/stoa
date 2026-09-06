package com.smartnotebook.core.model.setup

public object WizardMachine {
    public fun reduce(
        state: WizardState,
        event: WizardEvent,
    ): WizardState =
        when (event) {
            WizardEvent.Reset -> WizardState(state.revision)
            WizardEvent.ProbePassed -> state.probePassed()
            is WizardEvent.ProbeFailed -> state.probeFailed(event.detail)
            is WizardEvent.ProbeBlocked -> state.probeBlocked(event.detail)
            WizardEvent.GoBack -> state.goBack()
            WizardEvent.RetryStep -> state.clearStepFault()
            WizardEvent.NotificationDenied -> state
            WizardEvent.MicrophoneDenied -> state
            else -> state.navigateFor(event)
        }

    private fun WizardState.navigateFor(event: WizardEvent): WizardState {
        val target =
            when (event) {
                WizardEvent.WelcomeAccepted -> WizardStep.SERVER
                WizardEvent.ServerAddressSubmitted -> WizardStep.TLS
                WizardEvent.NotificationGranted -> WizardStep.PUSH_OPTIONAL
                WizardEvent.PushEnabled -> WizardStep.MICROPHONE
                WizardEvent.PushSkipped -> WizardStep.MICROPHONE
                WizardEvent.MicrophoneGranted -> WizardStep.AUDIO_TEST
                else -> return this
            }
        return advanceTo(target)
    }

    private fun WizardState.advanceTo(target: WizardStep): WizardState {
        if (step != target.previous) {
            return this
        }
        return copy(
            step = target,
            lastSafeStep = step,
            stepRunning = false,
            stepError = null,
            profileConfirmed = profileConfirmed || target == WizardStep.INSTALLATION,
        )
    }

    private fun WizardState.probePassed(): WizardState {
        if (!step.isProbeStep) {
            return this
        }
        return advanceTo(checkNotNull(step.next))
    }

    private fun WizardState.probeFailed(detail: String): WizardState {
        if (!step.isProbeStep) {
            return this
        }
        return copy(stepRunning = false, stepError = detail)
    }

    private fun WizardState.probeBlocked(detail: String): WizardState {
        if (!step.isProbeStep) {
            return this
        }
        return copy(stepRunning = false, stepError = detail, blocked = true)
    }

    private fun WizardState.goBack(): WizardState {
        val previous = step.previous
        val target = if (step > lastSafeStep) lastSafeStep else previous ?: step
        return copy(step = target, stepRunning = false, stepError = null)
    }

    private fun WizardState.clearStepFault(): WizardState = copy(stepRunning = false, stepError = null)
}
