package com.smartnotebook.feature.setup

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.smartnotebook.core.model.ClientPreferences
import com.smartnotebook.core.model.ServerProfile
import com.smartnotebook.core.model.setup.ValidatedServerAddress
import com.smartnotebook.core.model.setup.WizardEvent
import com.smartnotebook.core.model.setup.WizardState
import com.smartnotebook.data.config.ConfigRepository
import com.smartnotebook.data.wizard.ServerSubmissionResult
import com.smartnotebook.data.wizard.WizardController
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

public class WizardViewModel(
    private val controller: WizardController,
    configRepository: ConfigRepository,
) : ViewModel() {
    public data class FormState(
        val scheme: String = ValidatedServerAddress.SCHEME_HTTPS,
        val profileName: String = "",
        val host: String = "",
        val port: String = "",
        val basePath: String = "",
        val deviceName: String = "",
        val language: String = ClientPreferences.DEFAULT_LANGUAGE,
        val audioQualityProfile: String = ClientPreferences.DEFAULT_AUDIO_QUALITY_PROFILE,
        val requestTimeoutSeconds: String = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        val connectionTimeoutSeconds: String = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    )

    public enum class FormError {
        SCHEME,
        PROFILE_NAME,
        HOST,
        PORT,
        BASE_PATH,
        DEVICE_NAME,
        LANGUAGE,
        AUDIO_PROFILE,
        REQUEST_TIMEOUT,
        CONNECTION_TIMEOUT,
    }

    public val wizard: StateFlow<WizardState> = controller.state

    private val _form = MutableStateFlow(FormState())

    public val form: StateFlow<FormState> = _form.asStateFlow()

    private val _submissionError = MutableStateFlow(false)

    public val submissionError: StateFlow<Boolean> = _submissionError.asStateFlow()

    public val formErrors: StateFlow<Set<FormError>> =
        _form
            .map { WizardFormValidation.computeFormErrors(it) }
            .stateIn(viewModelScope, SharingStarted.Eagerly, emptySet())

    init {
        viewModelScope.launch {
            val profile = configRepository.serverProfile.first()
            val preferences = configRepository.preferences.first()
            _form.value =
                FormState(
                    profileName = profile?.name.orEmpty(),
                    host =
                        profile
                            ?.host
                            ?.removePrefix(IPV6_OPEN_BRACKET)
                            ?.removeSuffix(IPV6_CLOSE_BRACKET)
                            .orEmpty(),
                    port = profile?.port?.toString().orEmpty(),
                    basePath = profile?.basePath.orEmpty(),
                    deviceName = preferences.deviceName.orEmpty(),
                    language = preferences.language,
                    audioQualityProfile = preferences.audioQualityProfile,
                    requestTimeoutSeconds =
                        profile
                            ?.requestTimeoutMillis
                            ?.let { (it / MILLIS_PER_SECOND).toString() }
                            .orEmpty()
                            .ifEmpty { DEFAULT_REQUEST_TIMEOUT_SECONDS },
                    connectionTimeoutSeconds =
                        profile
                            ?.connectionTimeoutMillis
                            ?.let { (it / MILLIS_PER_SECOND).toString() }
                            .orEmpty()
                            .ifEmpty { DEFAULT_CONNECTION_TIMEOUT_SECONDS },
                )
        }
    }

    public fun updateForm(transform: (FormState) -> FormState) {
        _form.update(transform)
    }

    public fun acceptWelcome() {
        controller.dispatch(WizardEvent.WelcomeAccepted)
    }

    public fun submitServerAddress() {
        val current = _form.value
        if (WizardFormValidation.computeFormErrors(current).isNotEmpty()) {
            return
        }
        val address = checkNotNull(WizardFormValidation.addressFor(current).address)
        viewModelScope.launch {
            val result =
                controller.submitServerAddress(
                    ServerProfile(
                        name = current.profileName.trim(),
                        scheme = address.scheme,
                        host = address.host,
                        port = address.port,
                        basePath = address.basePath,
                        requestTimeoutMillis =
                            checkNotNull(WizardFormValidation.parseTimeoutSeconds(current.requestTimeoutSeconds)) *
                                MILLIS_PER_SECOND,
                        connectionTimeoutMillis =
                            checkNotNull(WizardFormValidation.parseTimeoutSeconds(current.connectionTimeoutSeconds)) *
                                MILLIS_PER_SECOND,
                    ),
                    ClientPreferences(
                        language = current.language.trim(),
                        audioQualityProfile = current.audioQualityProfile.trim(),
                        deviceName = current.deviceName.trim().ifBlank { null },
                    ),
                )
            if (result is ServerSubmissionResult.CleartextNotAllowed) {
                _submissionError.value = true
            }
        }
    }

    public fun onGoBack() {
        controller.dispatch(WizardEvent.GoBack)
    }

    public fun onRetry() {
        controller.retry()
    }

    public val permissionActions: WizardPermissionActions = WizardPermissionActions(controller)

    public class WizardPermissionActions(
        private val controller: WizardController,
    ) {
        public fun onNotificationGranted() {
            controller.dispatch(WizardEvent.NotificationGranted)
        }

        public fun onNotificationDenied() {
            controller.dispatch(WizardEvent.NotificationDenied)
        }

        public fun onPushEnabled() {
            controller.dispatch(WizardEvent.PushEnabled)
        }

        public fun onPushSkipped() {
            controller.dispatch(WizardEvent.PushSkipped)
        }

        public fun onMicrophoneGranted() {
            controller.dispatch(WizardEvent.MicrophoneGranted)
        }

        public fun onMicrophoneDenied() {
            controller.dispatch(WizardEvent.MicrophoneDenied)
        }
    }

    private companion object {
        private const val MILLIS_PER_SECOND = 1000L
        private const val DEFAULT_REQUEST_TIMEOUT_SECONDS = "30"
        private const val DEFAULT_CONNECTION_TIMEOUT_SECONDS = "10"
        private const val IPV6_OPEN_BRACKET = "["
        private const val IPV6_CLOSE_BRACKET = "]"
    }
}
