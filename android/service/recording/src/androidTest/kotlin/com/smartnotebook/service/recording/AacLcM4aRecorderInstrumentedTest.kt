package com.smartnotebook.service.recording

import android.content.Context
import android.media.MediaFormat
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.google.common.truth.Truth.assertThat
import org.junit.After
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class AacLcM4aRecorderInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()
    private val output = File(context.cacheDir, "audio-risk-prototype.m4a")

    @Test
    fun recordsReadableAacLcM4aSegment() {
        val result =
            AacLcM4aRecorder().record(
                context = context,
                outputFile = output,
                targetDurationMs = AacLcM4aRecorder.DEFAULT_TARGET_DURATION_MS,
            )

        if (result !is AacLcM4aRecorder.RecordingResult.Success) {
            fail("recording failed with $result")
            return
        }

        assertThat(result.file.exists()).isTrue()
        assertThat(result.file.length()).isGreaterThan(0L)
        assertThat(result.pcmBytes)
            .isEqualTo(result.requestedDurationMs * AacLcM4aRecorder.SAMPLE_RATE_HZ * 2L / 1_000L)
        assertThat(result.encodedSampleBytes).isGreaterThan(0L)
        assertThat(result.sha256Hex).isEqualTo(sha256Hex(result.file))
        assertThat(result.metadata.mimeType).isEqualTo(MediaFormat.MIMETYPE_AUDIO_AAC)
        assertThat(result.metadata.sampleRateHz).isEqualTo(AacLcM4aRecorder.SAMPLE_RATE_HZ)
        assertThat(result.metadata.channelCount).isEqualTo(AacLcM4aRecorder.CHANNEL_COUNT)
        assertThat(result.metadata.bitRateBps).isGreaterThan(0)
        assertThat(result.metadata.isAacLc).isTrue()
        assertThat(abs(result.metadata.durationMs - result.requestedDurationMs)).isAtMost(25L)
    }

    @After
    fun deleteOutput() {
        output.delete()
    }
}
