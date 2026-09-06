package com.smartnotebook.core.model.setup

public data class WizardState(
    val revision: Int = REVISION,
    val step: WizardStep = WizardStep.WELCOME,
    val lastSafeStep: WizardStep = WizardStep.WELCOME,
    val profileConfirmed: Boolean = false,
    val blocked: Boolean = false,
    val stepRunning: Boolean = false,
    val stepError: String? = null,
) {
    public val isCompleted: Boolean
        get() = step == WizardStep.COMPLETED

    public companion object {
        public const val REVISION: Int = 1

        public val INITIAL: WizardState = WizardState()
    }
}
