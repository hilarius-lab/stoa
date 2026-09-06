package com.smartnotebook.core.designsystem

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.github.takahirom.roborazzi.captureRoboImage
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

private val goldenScreenPadding = 24.dp
private val goldenContentSpacing = 16.dp

private const val GOLDEN_DEVICE_QUALIFIERS = "w360dp-h640dp-normal-notlong-port-xhdpi"

@RunWith(AndroidJUnit4::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@Config(sdk = [36], qualifiers = GOLDEN_DEVICE_QUALIFIERS)
class SmartNotebookDesignSystemGoldenTest {
    @Test
    fun themeAndCardPhoneGolden() {
        captureRoboImage {
            SmartNotebookTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    Column(
                        modifier =
                            Modifier.fillMaxSize().padding(goldenScreenPadding),
                        verticalArrangement = Arrangement.spacedBy(goldenContentSpacing),
                    ) {
                        Text(
                            text = "Smart Notebook",
                            style = MaterialTheme.typography.headlineMedium,
                        )
                        Text(
                            text = "Designsystem",
                            style = MaterialTheme.typography.bodyLarge,
                        )
                        SmartNotebookCard(
                            title = "Notiz",
                            body = "Beispielinhalt für den Golden-Test",
                        )
                    }
                }
            }
        }
    }
}
