package com.smartnotebook.feature.setup

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.smartnotebook.core.model.setup.WizardState
import com.smartnotebook.core.model.setup.WizardStep

@Composable
internal fun WizardField(
    label: String,
    value: String,
    isError: Boolean,
    keyboardType: KeyboardType,
    onValueChange: (String) -> Unit,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        singleLine = true,
        isError = isError,
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        modifier = Modifier.fillMaxWidth(),
    )
}

@Composable
internal fun ProbeStep(
    wizard: WizardState,
    onRetry: () -> Unit,
) {
    val stepError = wizard.stepError
    WizardStepTitle(stringResource(stepTitleResId(wizard.step)))
    when {
        wizard.stepRunning ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(ITEM_SPACING),
            ) {
                CircularProgressIndicator()
                Text(text = stringResource(R.string.probe_running))
            }
        stepError != null -> {
            Text(
                text = stepError,
                style = MaterialTheme.typography.bodyLarge,
                color =
                    if (wizard.blocked) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
            )
            Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.action_retry))
            }
        }
    }
}

@Composable
internal fun PermissionStep(
    title: String,
    text: String,
    actionLabel: String,
    onAction: () -> Unit,
) {
    WizardStepTitle(title)
    Text(text = text, style = MaterialTheme.typography.bodyLarge)
    Button(onClick = onAction, modifier = Modifier.fillMaxWidth()) {
        Text(actionLabel)
    }
}

@Composable
internal fun PushOptionalStep(
    onEnable: () -> Unit,
    onSkip: () -> Unit,
) {
    WizardStepTitle(stringResource(R.string.step_push_optional_title))
    Text(
        text = stringResource(R.string.step_push_optional_text),
        style = MaterialTheme.typography.bodyLarge,
    )
    Button(onClick = onEnable, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.action_enable_push))
    }
    OutlinedButton(onClick = onSkip, modifier = Modifier.fillMaxWidth()) {
        Text(stringResource(R.string.action_skip))
    }
}

@Composable
internal fun CompletedStep() {
    WizardStepTitle(stringResource(R.string.step_completed_title))
    Text(
        text = stringResource(R.string.step_completed_text),
        style = MaterialTheme.typography.bodyLarge,
    )
}

@Composable
internal fun WizardStepTitle(text: String) {
    Text(text = text, style = MaterialTheme.typography.headlineSmall)
}

private fun stepTitleResId(step: WizardStep): Int =
    when (step) {
        WizardStep.TLS -> R.string.step_tls_title
        WizardStep.CAPABILITIES -> R.string.step_capabilities_title
        WizardStep.COMPATIBILITY -> R.string.step_compatibility_title
        WizardStep.INSTALLATION -> R.string.step_installation_title
        WizardStep.AUDIO_TEST -> R.string.step_audio_test_title
        WizardStep.UPLOAD_ACK_TEST -> R.string.step_upload_ack_title
        WizardStep.INITIAL_SYNC -> R.string.step_initial_sync_title
        else -> R.string.step_tls_title
    }
