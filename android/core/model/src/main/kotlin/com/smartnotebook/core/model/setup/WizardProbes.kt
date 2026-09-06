package com.smartnotebook.core.model.setup

import com.smartnotebook.core.model.ClientPreferences
import com.smartnotebook.core.model.ServerProfile

public sealed interface ProbeOutcome {
    public data object Passed : ProbeOutcome

    public data class Failed(
        val detail: String,
    ) : ProbeOutcome

    public data class Blocked(
        val detail: String,
    ) : ProbeOutcome
}

public interface WizardProbe {
    public suspend fun run(
        profile: ServerProfile,
        preferences: ClientPreferences,
    ): ProbeOutcome
}

public interface WizardTlsProbe : WizardProbe

public interface WizardCapabilitiesProbe : WizardProbe

public interface WizardCompatibilityProbe : WizardProbe

public interface WizardInstallationProbe : WizardProbe

public interface WizardAudioTestProbe : WizardProbe

public interface WizardUploadAckProbe : WizardProbe

public interface WizardInitialSyncProbe : WizardProbe

public data class WizardProbes(
    val tls: WizardTlsProbe,
    val capabilities: WizardCapabilitiesProbe,
    val compatibility: WizardCompatibilityProbe,
    val installation: WizardInstallationProbe,
    val audioTest: WizardAudioTestProbe,
    val uploadAck: WizardUploadAckProbe,
    val initialSync: WizardInitialSyncProbe,
)
