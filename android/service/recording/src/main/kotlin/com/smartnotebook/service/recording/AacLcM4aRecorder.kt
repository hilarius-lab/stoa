package com.smartnotebook.service.recording

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.media.MediaRecorder
import com.smartnotebook.core.model.ClientErrorCode
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import kotlin.math.abs

@Suppress("TooManyFunctions")
public class AacLcM4aRecorder {
    public sealed interface RecordingResult {
        public data class Success(
            public val file: File,
            public val source: Int,
            public val sourceName: String,
            public val requestedDurationMs: Long,
            public val pcmBytes: Long,
            public val encodedSampleBytes: Long,
            public val sha256Hex: String,
            public val metadata: M4aSegmentMetadata,
        ) : RecordingResult

        public data class Failure(
            public val code: ClientErrorCode,
            public val detail: String,
        ) : RecordingResult
    }

    @Suppress("ReturnCount", "TooGenericExceptionCaught", "SwallowedException")
    public fun record(
        context: Context,
        outputFile: File,
        targetDurationMs: Long = DEFAULT_TARGET_DURATION_MS,
    ): RecordingResult {
        if (targetDurationMs <= 0L) {
            return RecordingResult.Failure(ClientErrorCode.VALIDATION_FAILED, "targetDurationMs")
        }

        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return RecordingResult.Failure(ClientErrorCode.MIC_PERMISSION_REQUIRED, "RECORD_AUDIO")
        }

        val targetBytes = targetDurationMs * SAMPLE_RATE_HZ * BYTES_PER_PCM_SAMPLE / MILLIS_PER_SECOND
        if (targetBytes !in 1L..Int.MAX_VALUE.toLong()) {
            return RecordingResult.Failure(ClientErrorCode.VALIDATION_FAILED, "targetDurationMs")
        }

        val minBufferSize =
            AudioRecord.getMinBufferSize(
                SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
        if (minBufferSize <= 0) {
            return RecordingResult.Failure(ClientErrorCode.RECORDER_INIT_FAILED, "minBufferSize=$minBufferSize")
        }

        val initialized = createRecorder(minBufferSize.coerceAtLeast(MIN_BUFFER_BYTES))
        if (initialized == null) {
            return RecordingResult.Failure(ClientErrorCode.RECORDER_INIT_FAILED, "source")
        }

        try {
            initialized.recorder.startRecording()
            val pcm = ByteArray(targetBytes.toInt())
            var offset = 0
            while (offset < pcm.size) {
                val read = initialized.recorder.read(pcm, offset, pcm.size - offset)
                if (read <= 0) {
                    return RecordingResult.Failure(ClientErrorCode.RECORDER_DIED, "read=$read")
                }
                offset += read
            }

            return encodeAndMux(
                pcm = pcm,
                outputFile = outputFile,
                source = CandidateSource(initialized.source, initialized.sourceName),
                targetDurationMs = targetDurationMs,
            )
        } catch (_: SecurityException) {
            return RecordingResult.Failure(ClientErrorCode.MIC_PERMISSION_REQUIRED, "RECORD_AUDIO")
        } catch (_: IOException) {
            return RecordingResult.Failure(ClientErrorCode.STORAGE_FULL, "io")
        } catch (_: Exception) {
            return RecordingResult.Failure(ClientErrorCode.RECORDER_DIED, "capture")
        } finally {
            runCatching { initialized.recorder.stop() }
            runCatching { initialized.recorder.release() }
        }
    }

    @SuppressLint("MissingPermission")
    private fun createRecorder(bufferSize: Int): InitializedRecorder? {
        val candidates =
            listOf(
                CandidateSource(MediaRecorder.AudioSource.VOICE_RECOGNITION, "VOICE_RECOGNITION"),
                CandidateSource(MediaRecorder.AudioSource.MIC, "MIC"),
            )

        for (candidate in candidates) {
            val recorder =
                runCatching {
                    AudioRecord(
                        candidate.source,
                        SAMPLE_RATE_HZ,
                        AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT,
                        bufferSize,
                    )
                }.getOrNull()

            if (recorder != null && recorder.state == AudioRecord.STATE_INITIALIZED) {
                return InitializedRecorder(recorder, candidate.source, candidate.sourceName)
            }

            recorder?.release()
        }

        return null
    }

    @Suppress("ReturnCount")
    private fun encodeAndMux(
        pcm: ByteArray,
        outputFile: File,
        source: CandidateSource,
        targetDurationMs: Long,
    ): RecordingResult {
        outputFile.parentFile?.mkdirs()
        var trimSamples = 0L

        repeat(MAX_DURATION_ATTEMPTS) {
            val encodedPcm = trimPcmBySamples(pcm, trimSamples)
            when (val result = encodeOnce(encodedPcm, pcm, outputFile, source, targetDurationMs)) {
                is RecordingResult.Failure -> return result
                is RecordingResult.Success -> {
                    val deviationMs = abs(result.metadata.durationMs - targetDurationMs)
                    if (deviationMs <= MAX_DURATION_DEVIATION_MS) {
                        return result
                    }
                    val deviationSamples = deviationMs * SAMPLE_RATE_HZ / MILLIS_PER_SECOND
                    if (result.metadata.durationMs > targetDurationMs) {
                        trimSamples += maxOf(AAC_FRAME_SAMPLES, deviationSamples)
                    } else {
                        trimSamples = (trimSamples - maxOf(AAC_FRAME_SAMPLES, deviationSamples)).coerceAtLeast(0L)
                    }
                }
            }
        }

        return RecordingResult.Failure(ClientErrorCode.SEGMENT_INVALID, "duration")
    }

    @Suppress("ReturnCount", "TooGenericExceptionCaught", "SwallowedException")
    private fun encodeOnce(
        encodedPcm: ByteArray,
        capturedPcm: ByteArray,
        outputFile: File,
        source: CandidateSource,
        targetDurationMs: Long,
    ): RecordingResult {
        val encoder = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
        val sink = MuxerSink(MediaMuxer(outputFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4))

        try {
            encoder.configure(createEncoderFormat(), null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            encoder.start()

            encodePcm(encoder, encodedPcm, sink::onFormat, sink::onSample)

            if (!sink.started) {
                return RecordingResult.Failure(ClientErrorCode.ENCODER_FAILED, "no-output")
            }

            sink.stop()

            val metadata =
                M4aSegmentValidator.validate(outputFile)
                    ?: return RecordingResult.Failure(ClientErrorCode.SEGMENT_INVALID, "metadata")

            return RecordingResult.Success(
                file = outputFile,
                source = source.source,
                sourceName = source.sourceName,
                requestedDurationMs = targetDurationMs,
                pcmBytes = capturedPcm.size.toLong(),
                encodedSampleBytes = sink.sampleBytes,
                sha256Hex = sha256Hex(outputFile),
                metadata = metadata,
            )
        } catch (_: IOException) {
            return RecordingResult.Failure(ClientErrorCode.STORAGE_FULL, "io")
        } catch (exception: Exception) {
            return RecordingResult.Failure(ClientErrorCode.ENCODER_FAILED, exceptionDiagnostic(exception))
        } finally {
            runCatching { encoder.stop() }
            runCatching { encoder.release() }
            sink.stopSafely()
            sink.releaseSafely()
        }
    }

    private fun createEncoderFormat(): MediaFormat {
        val encoderFormat =
            MediaFormat.createAudioFormat(
                MediaFormat.MIMETYPE_AUDIO_AAC,
                SAMPLE_RATE_HZ,
                CHANNEL_COUNT,
            )
        encoderFormat.setInteger(
            MediaFormat.KEY_AAC_PROFILE,
            MediaCodecInfo.CodecProfileLevel.AACObjectLC,
        )
        encoderFormat.setInteger(MediaFormat.KEY_BIT_RATE, BIT_RATE_BPS)
        return encoderFormat
    }

    private fun trimPcmBySamples(
        pcm: ByteArray,
        samples: Long,
    ): ByteArray {
        val trimmedBytes = (samples.coerceAtLeast(0L) * BYTES_PER_PCM_SAMPLE).toInt()
        val encodedSize = (pcm.size - trimmedBytes).coerceIn(MIN_ENCODED_PCM_BYTES, pcm.size)
        return if (encodedSize == pcm.size) pcm else pcm.copyOfRange(0, encodedSize)
    }

    private fun encodePcm(
        encoder: MediaCodec,
        pcm: ByteArray,
        onFormat: (MediaFormat) -> Unit,
        onSample: (ByteBuffer, MediaCodec.BufferInfo) -> Unit,
    ) {
        var inputOffset = 0
        while (inputOffset < pcm.size) {
            val requested = minOf(MAX_INPUT_CHUNK_BYTES, pcm.size - inputOffset)
            val chunk = PcmChunk(inputOffset, requested, ptsUsFor(inputOffset))
            val consumed = queueInput(encoder, pcm, chunk, false)
            if (consumed <= 0) {
                drainOutput(encoder, onFormat, onSample, DRAIN_TIMEOUT_US)
                continue
            }
            inputOffset += consumed
            drainOutput(encoder, onFormat, onSample, NO_TIMEOUT_US)
        }

        queueInput(encoder, pcm, PcmChunk(0, 0, ptsUsFor(pcm.size)), true)

        var sawEndOfStream = false
        while (!sawEndOfStream) {
            sawEndOfStream = drainOutput(encoder, onFormat, onSample, DRAIN_TIMEOUT_US)
        }
    }

    private fun ptsUsFor(byteOffset: Int): Long =
        (byteOffset / BYTES_PER_PCM_SAMPLE) * MICROS_PER_SECOND / SAMPLE_RATE_HZ

    private fun exceptionDiagnostic(exception: Exception): String {
        val frames = exception.stackTrace.take(DIAGNOSTIC_FRAME_COUNT).joinToString(" | ") { it.toString() }
        return "${exception.javaClass.simpleName}:${exception.message} | $frames".take(DIAGNOSTIC_DETAIL_LIMIT)
    }

    private fun queueInput(
        encoder: MediaCodec,
        pcm: ByteArray,
        chunk: PcmChunk,
        endOfStream: Boolean,
    ): Int {
        val flags = if (endOfStream) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0
        val index = encoder.dequeueInputBuffer(INPUT_TIMEOUT_US)
        check(index >= 0) { "encoder input unavailable" }

        val buffer = encoder.getInputBuffer(index)
        checkNotNull(buffer) { "encoder input buffer missing" }

        val size = if (chunk.size == 0) 0 else minOf(chunk.size, buffer.remaining())
        if (size > 0) {
            buffer.put(pcm, chunk.offset, size)
        }

        encoder.queueInputBuffer(index, 0, size, chunk.ptsUs, flags)
        return size
    }

    private fun drainOutput(
        encoder: MediaCodec,
        onFormat: (MediaFormat) -> Unit,
        onSample: (ByteBuffer, MediaCodec.BufferInfo) -> Unit,
        timeoutUs: Long,
    ): Boolean {
        val info = MediaCodec.BufferInfo()
        var endOfStream = false
        var active = true

        while (active) {
            val index = encoder.dequeueOutputBuffer(info, timeoutUs)
            when {
                index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> onFormat(encoder.outputFormat)
                index >= 0 -> {
                    val buffer = checkNotNull(encoder.getOutputBuffer(index)) { "encoder output buffer missing" }
                    val size = info.size
                    if (size > 0 && (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        buffer.position(info.offset)
                        buffer.limit(info.offset + info.size)
                        onSample(buffer, info)
                    }
                    encoder.releaseOutputBuffer(index, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                        endOfStream = true
                        active = false
                    }
                }
                index == MediaCodec.INFO_TRY_AGAIN_LATER -> active = false
                else -> error("encoder output status $index")
            }
        }

        return endOfStream
    }

    private class MuxerSink(
        private val muxer: MediaMuxer,
    ) {
        var started: Boolean = false
            private set
        var sampleBytes: Long = 0L
            private set

        private var trackIndex = -1
        private var stopped = false

        fun onFormat(format: MediaFormat) {
            trackIndex = muxer.addTrack(format)
            muxer.start()
            started = true
        }

        fun onSample(
            buffer: ByteBuffer,
            info: MediaCodec.BufferInfo,
        ) {
            check(trackIndex >= 0) { "muxer track missing" }
            muxer.writeSampleData(trackIndex, buffer, info)
            sampleBytes += info.size.toLong()
        }

        fun stop() {
            if (started && !stopped) {
                muxer.stop()
                stopped = true
            }
        }

        fun stopSafely() {
            if (started && !stopped) {
                runCatching { muxer.stop() }
                stopped = true
            }
        }

        fun releaseSafely() {
            runCatching { muxer.release() }
        }
    }

    private data class PcmChunk(
        val offset: Int,
        val size: Int,
        val ptsUs: Long,
    )

    private data class InitializedRecorder(
        val recorder: AudioRecord,
        val source: Int,
        val sourceName: String,
    )

    private data class CandidateSource(
        val source: Int,
        val sourceName: String,
    )

    public companion object {
        public const val SAMPLE_RATE_HZ: Int = 48_000
        public const val CHANNEL_COUNT: Int = 1
        public const val BIT_RATE_BPS: Int = 64_000
        public const val DEFAULT_TARGET_DURATION_MS: Long = 10_000L

        private const val MILLIS_PER_SECOND: Long = 1_000L
        private const val MICROS_PER_SECOND: Long = 1_000_000L
        private const val BYTES_PER_PCM_SAMPLE: Long = 2L
        private const val MIN_BUFFER_BYTES: Int = 8_192
        private const val MAX_INPUT_CHUNK_BYTES: Int = 65_536
        private const val INPUT_TIMEOUT_US: Long = 100_000L
        private const val NO_TIMEOUT_US: Long = 0L
        private const val DRAIN_TIMEOUT_US: Long = 10_000L
        private const val MIN_ENCODED_PCM_BYTES: Int = 2_048
        private const val AAC_FRAME_SAMPLES: Long = 1_024L
        private const val MAX_DURATION_DEVIATION_MS: Long = 22L
        private const val MAX_DURATION_ATTEMPTS: Int = 4
        private const val DIAGNOSTIC_FRAME_COUNT: Int = 3
        private const val DIAGNOSTIC_DETAIL_LIMIT: Int = 240
    }
}
