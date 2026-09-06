package com.smartnotebook.feature.setup

import com.smartnotebook.core.model.setup.ServerAddressError
import com.smartnotebook.core.model.setup.ServerAddressInput
import com.smartnotebook.core.model.setup.ServerAddressValidation
import com.smartnotebook.core.model.setup.ServerAddressValidator

internal object WizardFormValidation {
    fun addressFor(form: WizardViewModel.FormState): ServerAddressValidation =
        ServerAddressValidator.validate(
            ServerAddressInput(
                scheme = form.scheme,
                host = form.host,
                port = form.port,
                basePath = form.basePath,
            ),
        )

    fun computeFormErrors(form: WizardViewModel.FormState): Set<WizardViewModel.FormError> {
        val errors = mutableSetOf<WizardViewModel.FormError>()
        addAddressErrors(form, errors)
        addDeviceErrors(form, errors)
        return errors
    }

    fun parseTimeoutSeconds(raw: String): Long? {
        val value =
            raw
                .trim()
                .takeIf { it.isNotEmpty() && it.all { digit -> digit in DIGITS } }
                ?.toLongOrNull()
        return value?.takeIf { it in MIN_TIMEOUT_SECONDS..MAX_TIMEOUT_SECONDS }
    }

    private fun addAddressErrors(
        form: WizardViewModel.FormState,
        errors: MutableSet<WizardViewModel.FormError>,
    ) {
        val validation = addressFor(form)
        if (ServerAddressError.SCHEME in validation.errors) {
            errors += WizardViewModel.FormError.SCHEME
        }
        if (form.profileName.isBlank()) {
            errors += WizardViewModel.FormError.PROFILE_NAME
        }
        if (ServerAddressError.HOST in validation.errors) {
            errors += WizardViewModel.FormError.HOST
        }
        if (ServerAddressError.PORT in validation.errors) {
            errors += WizardViewModel.FormError.PORT
        }
        if (ServerAddressError.BASE_PATH in validation.errors) {
            errors += WizardViewModel.FormError.BASE_PATH
        }
    }

    private fun addDeviceErrors(
        form: WizardViewModel.FormState,
        errors: MutableSet<WizardViewModel.FormError>,
    ) {
        if (form.deviceName.isBlank()) {
            errors += WizardViewModel.FormError.DEVICE_NAME
        }
        if (form.language.isBlank()) {
            errors += WizardViewModel.FormError.LANGUAGE
        }
        if (form.audioQualityProfile.isBlank()) {
            errors += WizardViewModel.FormError.AUDIO_PROFILE
        }
        if (parseTimeoutSeconds(form.requestTimeoutSeconds) == null) {
            errors += WizardViewModel.FormError.REQUEST_TIMEOUT
        }
        if (parseTimeoutSeconds(form.connectionTimeoutSeconds) == null) {
            errors += WizardViewModel.FormError.CONNECTION_TIMEOUT
        }
    }

    private const val MIN_TIMEOUT_SECONDS = 1L
    private const val MAX_TIMEOUT_SECONDS = 300L
    private val DIGITS = '0'..'9'
}
