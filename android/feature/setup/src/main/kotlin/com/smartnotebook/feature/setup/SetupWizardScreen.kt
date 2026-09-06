package com.smartnotebook.feature.setup

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.smartnotebook.core.model.setup.ValidatedServerAddress
import com.smartnotebook.core.model.setup.WizardState
import com.smartnotebook.core.model.setup.WizardStep

@Composable
public fun SetupWizardScreen(
    viewModel: WizardViewModel,
    modifier: Modifier = Modifier,
) {
    val wizard by viewModel.wizard.collectAsState()

    val notificationPermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                viewModel.permissionActions.onNotificationGranted()
            } else {
                viewModel.permissionActions.onNotificationDenied()
            }
        }
    val microphonePermission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                viewModel.permissionActions.onMicrophoneGranted()
            } else {
                viewModel.permissionActions.onMicrophoneDenied()
            }
        }

    Scaffold(
        topBar = {
            WizardTopBar(
                canGoBack = wizard.step != WizardStep.WELCOME,
                onGoBack = viewModel::onGoBack,
            )
        },
    ) { innerPadding ->
        Column(
            modifier =
                modifier
                    .fillMaxSize()
                    .padding(innerPadding)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = CONTENT_PADDING),
            verticalArrangement = Arrangement.spacedBy(ITEM_SPACING),
        ) {
            WizardProgress(wizard)
            WizardStepContent(
                wizard = wizard,
                viewModel = viewModel,
                onNotificationPermission = {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
                    } else {
                        viewModel.permissionActions.onNotificationGranted()
                    }
                },
                onMicrophonePermission = {
                    microphonePermission.launch(Manifest.permission.RECORD_AUDIO)
                },
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WizardTopBar(
    canGoBack: Boolean,
    onGoBack: () -> Unit,
) {
    TopAppBar(
        title = { Text(stringResource(R.string.wizard_title)) },
        navigationIcon = {
            if (canGoBack) {
                TextButton(onClick = onGoBack) {
                    Text(stringResource(R.string.action_back))
                }
            }
        },
    )
}

@Composable
private fun WizardProgress(wizard: WizardState) {
    val total = WizardStep.entries.size
    Text(
        text = stringResource(R.string.wizard_progress, wizard.step.ordinal + 1, total),
        style = MaterialTheme.typography.labelMedium,
    )
    LinearProgressIndicator(
        progress = { (wizard.step.ordinal + 1).toFloat() / total },
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
private fun WizardStepContent(
    wizard: WizardState,
    viewModel: WizardViewModel,
    onNotificationPermission: () -> Unit,
    onMicrophonePermission: () -> Unit,
) {
    when {
        wizard.step == WizardStep.WELCOME -> WelcomeStep(onContinue = viewModel::acceptWelcome)
        wizard.step == WizardStep.SERVER -> ServerStep(viewModel)
        wizard.step.isProbeStep -> ProbeStep(wizard = wizard, onRetry = viewModel::onRetry)
        wizard.step == WizardStep.NOTIFICATION ->
            PermissionStep(
                title = stringResource(R.string.step_notification_title),
                text = stringResource(R.string.step_notification_text),
                actionLabel = stringResource(R.string.action_allow_notification),
                onAction = onNotificationPermission,
            )
        wizard.step == WizardStep.PUSH_OPTIONAL ->
            PushOptionalStep(
                onEnable = viewModel.permissionActions::onPushEnabled,
                onSkip = viewModel.permissionActions::onPushSkipped,
            )
        wizard.step == WizardStep.MICROPHONE ->
            PermissionStep(
                title = stringResource(R.string.step_microphone_title),
                text = stringResource(R.string.step_microphone_text),
                actionLabel = stringResource(R.string.action_allow_microphone),
                onAction = onMicrophonePermission,
            )
        else -> CompletedStep()
    }
}

@Composable
private fun WelcomeStep(onContinue: () -> Unit) {
    WizardStepTitle(stringResource(R.string.step_welcome_title))
    Text(
        text = stringResource(R.string.step_welcome_text),
        style = MaterialTheme.typography.bodyLarge,
    )
    Button(onClick = onContinue, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.action_continue))
    }
}

@Composable
private fun ServerStep(viewModel: WizardViewModel) {
    val form by viewModel.form.collectAsState()
    val formErrors by viewModel.formErrors.collectAsState()
    val submissionError by viewModel.submissionError.collectAsState()

    WizardStepTitle(stringResource(R.string.step_server_title))
    ServerAddressFields(form, formErrors, viewModel)
    ServerDeviceFields(form, formErrors, viewModel)
    if (submissionError) {
        Text(
            text = stringResource(R.string.error_cleartext),
            color = MaterialTheme.colorScheme.error,
        )
    }
    Button(
        onClick = viewModel::submitServerAddress,
        enabled = formErrors.isEmpty(),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(stringResource(R.string.action_continue))
    }
}

@Composable
private fun ServerAddressFields(
    form: WizardViewModel.FormState,
    formErrors: Set<WizardViewModel.FormError>,
    viewModel: WizardViewModel,
) {
    SchemeSelector(selected = form.scheme) { scheme ->
        viewModel.updateForm { current -> current.copy(scheme = scheme) }
    }
    WizardField(
        label = stringResource(R.string.field_profile_name),
        value = form.profileName,
        isError = WizardViewModel.FormError.PROFILE_NAME in formErrors,
        keyboardType = KeyboardType.Text,
    ) { value ->
        viewModel.updateForm { current -> current.copy(profileName = value) }
    }
    WizardField(
        label = stringResource(R.string.field_host),
        value = form.host,
        isError = WizardViewModel.FormError.HOST in formErrors,
        keyboardType = KeyboardType.Text,
    ) { value ->
        viewModel.updateForm { current -> current.copy(host = value) }
    }
    WizardField(
        label = stringResource(R.string.field_port),
        value = form.port,
        isError = WizardViewModel.FormError.PORT in formErrors,
        keyboardType = KeyboardType.Number,
    ) { value ->
        viewModel.updateForm { current -> current.copy(port = value) }
    }
    WizardField(
        label = stringResource(R.string.field_base_path),
        value = form.basePath,
        isError = WizardViewModel.FormError.BASE_PATH in formErrors,
        keyboardType = KeyboardType.Uri,
    ) { value ->
        viewModel.updateForm { current -> current.copy(basePath = value) }
    }
}

@Composable
private fun ServerDeviceFields(
    form: WizardViewModel.FormState,
    formErrors: Set<WizardViewModel.FormError>,
    viewModel: WizardViewModel,
) {
    WizardField(
        label = stringResource(R.string.field_device_name),
        value = form.deviceName,
        isError = WizardViewModel.FormError.DEVICE_NAME in formErrors,
        keyboardType = KeyboardType.Text,
    ) { value ->
        viewModel.updateForm { current -> current.copy(deviceName = value) }
    }
    WizardField(
        label = stringResource(R.string.field_language),
        value = form.language,
        isError = WizardViewModel.FormError.LANGUAGE in formErrors,
        keyboardType = KeyboardType.Text,
    ) { value ->
        viewModel.updateForm { current -> current.copy(language = value) }
    }
    WizardField(
        label = stringResource(R.string.field_audio_profile),
        value = form.audioQualityProfile,
        isError = WizardViewModel.FormError.AUDIO_PROFILE in formErrors,
        keyboardType = KeyboardType.Text,
    ) { value ->
        viewModel.updateForm { current -> current.copy(audioQualityProfile = value) }
    }
    WizardField(
        label = stringResource(R.string.field_request_timeout),
        value = form.requestTimeoutSeconds,
        isError = WizardViewModel.FormError.REQUEST_TIMEOUT in formErrors,
        keyboardType = KeyboardType.Number,
    ) { value ->
        viewModel.updateForm { current -> current.copy(requestTimeoutSeconds = value) }
    }
    WizardField(
        label = stringResource(R.string.field_connection_timeout),
        value = form.connectionTimeoutSeconds,
        isError = WizardViewModel.FormError.CONNECTION_TIMEOUT in formErrors,
        keyboardType = KeyboardType.Number,
    ) { value ->
        viewModel.updateForm { current -> current.copy(connectionTimeoutSeconds = value) }
    }
}

@Composable
private fun SchemeSelector(
    selected: String,
    onSelect: (String) -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        SchemeOption(
            label = stringResource(R.string.scheme_https),
            isSelected = selected == ValidatedServerAddress.SCHEME_HTTPS,
            onClick = { onSelect(ValidatedServerAddress.SCHEME_HTTPS) },
        )
        SchemeOption(
            label = stringResource(R.string.scheme_http),
            isSelected = selected == ValidatedServerAddress.SCHEME_HTTP,
            onClick = { onSelect(ValidatedServerAddress.SCHEME_HTTP) },
        )
    }
}

@Composable
private fun SchemeOption(
    label: String,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(SCHEME_OPTION_SPACING),
    ) {
        RadioButton(selected = isSelected, onClick = onClick)
        Text(text = label, style = MaterialTheme.typography.bodyLarge)
    }
}

internal val CONTENT_PADDING = 16.dp
internal val ITEM_SPACING = 16.dp
internal val SCHEME_OPTION_SPACING = 8.dp
