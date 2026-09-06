package com.smartnotebook.core.model.setup

import com.google.common.truth.Truth.assertThat
import org.junit.Test

class WizardMachineTest {
    @Test
    fun initialStateIsUnconfirmedWelcome() {
        assertThat(WizardState.INITIAL.step).isEqualTo(WizardStep.WELCOME)
        assertThat(WizardState.INITIAL.lastSafeStep).isEqualTo(WizardStep.WELCOME)
        assertThat(WizardState.INITIAL.profileConfirmed).isFalse()
        assertThat(WizardState.INITIAL.isCompleted).isFalse()
    }

    @Test
    fun fullHappyPathReachesCompleted() {
        val finalState = fullHappyPath()

        assertThat(finalState.step).isEqualTo(WizardStep.COMPLETED)
        assertThat(finalState.isCompleted).isTrue()
        assertThat(finalState.profileConfirmed).isTrue()
        assertThat(finalState.blocked).isFalse()
        assertThat(finalState.stepError).isNull()
    }

    @Test
    fun welcomeAdvancesToServerWithSafeStep() {
        val next = WizardMachine.reduce(WizardState.INITIAL, WizardEvent.WelcomeAccepted)

        assertThat(next.step).isEqualTo(WizardStep.SERVER)
        assertThat(next.lastSafeStep).isEqualTo(WizardStep.WELCOME)
    }

    @Test
    fun serverSubmissionAdvancesToTls() {
        val state = WizardMachine.reduce(WizardState.INITIAL, WizardEvent.WelcomeAccepted)
        val next = WizardMachine.reduce(state, WizardEvent.ServerAddressSubmitted)

        assertThat(next.step).isEqualTo(WizardStep.TLS)
        assertThat(next.lastSafeStep).isEqualTo(WizardStep.SERVER)
    }

    @Test
    fun compatibilityPassConfirmsProfile() {
        val beforeCompatibility =
            WizardMachine.reduce(
                WizardMachine.reduce(
                    WizardMachine.reduce(
                        WizardMachine.reduce(
                            WizardState.INITIAL,
                            WizardEvent.WelcomeAccepted,
                        ),
                        WizardEvent.ServerAddressSubmitted,
                    ),
                    WizardEvent.ProbePassed,
                ),
                WizardEvent.ProbePassed,
            )

        val afterCompatibility = WizardMachine.reduce(beforeCompatibility, WizardEvent.ProbePassed)

        assertThat(afterCompatibility.step).isEqualTo(WizardStep.INSTALLATION)
        assertThat(afterCompatibility.profileConfirmed).isTrue()
    }

    @Test
    fun probePassedOnlyAppliesOnProbeSteps() {
        val state = WizardState.INITIAL

        val next = WizardMachine.reduce(state, WizardEvent.ProbePassed)

        assertThat(next).isEqualTo(state)
    }

    @Test
    fun probeFailedKeepsStepAndStoresError() {
        val onTls =
            WizardMachine.reduce(
                WizardMachine.reduce(WizardState.INITIAL, WizardEvent.WelcomeAccepted),
                WizardEvent.ServerAddressSubmitted,
            )

        val next = WizardMachine.reduce(onTls, WizardEvent.ProbeFailed(TLS_ERROR_DETAIL))

        assertThat(next.step).isEqualTo(WizardStep.TLS)
        assertThat(next.stepError).isEqualTo(TLS_ERROR_DETAIL)
        assertThat(next.stepRunning).isFalse()
        assertThat(next.blocked).isFalse()
    }

    @Test
    fun probeBlockedMarksWizardAsBlocked() {
        val onTls =
            WizardMachine.reduce(
                WizardMachine.reduce(WizardState.INITIAL, WizardEvent.WelcomeAccepted),
                WizardEvent.ServerAddressSubmitted,
            )

        val next = WizardMachine.reduce(onTls, WizardEvent.ProbeBlocked(INCOMPATIBLE_DETAIL))

        assertThat(next.step).isEqualTo(WizardStep.TLS)
        assertThat(next.blocked).isTrue()
        assertThat(next.stepError).isEqualTo(INCOMPATIBLE_DETAIL)
    }

    @Test
    fun permissionDenialKeepsCurrentStep() {
        val onNotification = stateOn(WizardStep.NOTIFICATION)

        val afterDenial = WizardMachine.reduce(onNotification, WizardEvent.NotificationDenied)
        val onMicrophone = stateOn(WizardStep.MICROPHONE)
        val afterMicDenial = WizardMachine.reduce(onMicrophone, WizardEvent.MicrophoneDenied)

        assertThat(afterDenial.step).isEqualTo(WizardStep.NOTIFICATION)
        assertThat(afterMicDenial.step).isEqualTo(WizardStep.MICROPHONE)
    }

    @Test
    fun notificationGrantAdvancesToPushOptional() {
        val onNotification = stateOn(WizardStep.NOTIFICATION)

        val next = WizardMachine.reduce(onNotification, WizardEvent.NotificationGranted)

        assertThat(next.step).isEqualTo(WizardStep.PUSH_OPTIONAL)
        assertThat(next.lastSafeStep).isEqualTo(WizardStep.NOTIFICATION)
    }

    @Test
    fun pushDecisionAdvancesToMicrophone() {
        val onPush = stateOn(WizardStep.PUSH_OPTIONAL)

        val skipped = WizardMachine.reduce(onPush, WizardEvent.PushSkipped)
        val enabled = WizardMachine.reduce(onPush, WizardEvent.PushEnabled)

        assertThat(skipped.step).isEqualTo(WizardStep.MICROPHONE)
        assertThat(enabled.step).isEqualTo(WizardStep.MICROPHONE)
    }

    @Test
    fun goBackFromUnfinishedProbeStepReturnsToLastSafeStep() {
        val onTls =
            WizardMachine.reduce(
                WizardMachine.reduce(WizardState.INITIAL, WizardEvent.WelcomeAccepted),
                WizardEvent.ServerAddressSubmitted,
            )

        val next = WizardMachine.reduce(onTls, WizardEvent.GoBack)

        assertThat(next.step).isEqualTo(WizardStep.SERVER)
        assertThat(next.stepError).isNull()
    }

    @Test
    fun goBackOnWelcomeIsIgnored() {
        val next = WizardMachine.reduce(WizardState.INITIAL, WizardEvent.GoBack)

        assertThat(next).isEqualTo(WizardState.INITIAL)
    }

    @Test
    fun retryClearsStepFault() {
        val onTls =
            WizardMachine.reduce(
                WizardMachine.reduce(WizardState.INITIAL, WizardEvent.WelcomeAccepted),
                WizardEvent.ServerAddressSubmitted,
            )
        val failed = WizardMachine.reduce(onTls, WizardEvent.ProbeFailed(TLS_ERROR_DETAIL))

        val next = WizardMachine.reduce(failed, WizardEvent.RetryStep)

        assertThat(next.stepError).isNull()
        assertThat(next.stepRunning).isFalse()
    }

    @Test
    fun resetRestoresInitialStepAndKeepsRevision() {
        val completed = fullHappyPath()

        val next = WizardMachine.reduce(completed, WizardEvent.Reset)

        assertThat(next.step).isEqualTo(WizardStep.WELCOME)
        assertThat(next.revision).isEqualTo(WizardState.REVISION)
        assertThat(next.profileConfirmed).isFalse()
        assertThat(next.blocked).isFalse()
    }

    @Test
    fun outOfOrderEventsAreIgnored() {
        val state = WizardState.INITIAL

        val next = WizardMachine.reduce(state, WizardEvent.ServerAddressSubmitted)

        assertThat(next).isEqualTo(state)
    }

    private fun fullHappyPath(): WizardState =
        sequenceOf(
            WizardEvent.WelcomeAccepted,
            WizardEvent.ServerAddressSubmitted,
            WizardEvent.ProbePassed,
            WizardEvent.ProbePassed,
            WizardEvent.ProbePassed,
            WizardEvent.ProbePassed,
            WizardEvent.NotificationGranted,
            WizardEvent.PushSkipped,
            WizardEvent.MicrophoneGranted,
            WizardEvent.ProbePassed,
            WizardEvent.ProbePassed,
            WizardEvent.ProbePassed,
        ).fold(WizardState.INITIAL) { current, event -> WizardMachine.reduce(current, event) }

    private fun stateOn(step: WizardStep): WizardState =
        WizardState(
            step = step,
            lastSafeStep = step.previous ?: step,
        )

    private companion object {
        private const val TLS_ERROR_DETAIL = "TLS handshake failed"
        private const val INCOMPATIBLE_DETAIL = "Contract version 2 is not supported"
    }
}
