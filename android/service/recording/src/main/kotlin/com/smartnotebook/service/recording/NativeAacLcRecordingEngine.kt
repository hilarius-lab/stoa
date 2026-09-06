package com.smartnotebook.service.recording

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import com.smartnotebook.core.model.ClientErrorCode
import java.io.File
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

@Suppress("TooManyFunctions")
internal class NativeAacLcRecordingEngine : RecordingEngine {
    private val lock = Any()
    private val running = AtomicBoolean(false)
    private val failureRef = AtomicReference<RecordingEngineResult.Failure?>(null)
    private val segmentSequence = AtomicInteger(0)

    private var audioRecord: AudioRecord? = null
    private var readerThread: Thread? = null
    private var writer: StreamingM4aWriter? = null
    private var outputDirectory: File? = null
    private var sourceName = SOURCE_MIC

    override fun start(outputDirectory: File): RecordingEngineResult =
        synchronized(lock) { startInternal(outputDirectory) }

    override fun pause(): RecordingEngineResult = synchronized(lock) { pauseInternal() }

    override fun resume(): RecordingEngineResult =
        synchronized(lock) {
            val directory =
                outputDirectory
                    ?: return RecordingEngineResult.Failure(
                        ClientErrorCode.VALIDATION_FAILED,
                        "output-directory",
                    )
            if (running.get()) {
                return RecordingEngineResult.Success(sourceName)
            }
            startInternal(directory)
        }

    override fun stop(): RecordingEngineResult = synchronized(lock) { pauseInternal() }

    @Suppress("LongMethod", "ReturnCount", "TooGenericExceptionCaught", "SwallowedException")
    private fun startInternal(directory: File): RecordingEngineResult {
        if (running.get()) {
            return RecordingEngineResult.Success(sourceName)
        }

        failureRef.set(null)

        if (!directory.isDirectory && !directory.mkdirs()) {
            return RecordingEngineResult.Failure(ClientErrorCode.STORAGE_FULL, "output-directory")
        }

        val minBufferSize =
            AudioRecord.getMinBufferSize(
                AacLcM4aRecorder.SAMPLE_RATE_HZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
        if (minBufferSize <= 0) {
            return RecordingEngineResult.Failure(
                ClientErrorCode.RECORDER_INIT_FAILED,
                "min-buffer-size-$minBufferSize",
            )
        }

        val initialized =
            createRecorder(minBufferSize.coerceAtLeast(MIN_BUFFER_BYTES))
                ?: return RecordingEngineResult.Failure(
                    ClientErrorCode.RECORDER_INIT_FAILED,
                    "source",
                )

        val file = File(directory, "recording-${System.currentTimeMillis()}-${segmentSequence.incrementAndGet()}.m4a")
        val newWriter = StreamingM4aWriter(file)
        try {
            newWriter.start()
        } catch (_: IOException) {
            initialized.recorder.release()
            return RecordingEngineResult.Failure(ClientErrorCode.STORAGE_FULL, "writer")
        } catch (exception: Exception) {
            initialized.recorder.release()
            return RecordingEngineResult.Failure(ClientErrorCode.ENCODER_FAILED, diagnostic(exception))
        }

        audioRecord = initialized.recorder
        writer = newWriter
        outputDirectory = directory
        running.set(true)

        try {
            initialized.recorder.startRecording()
        } catch (_: SecurityException) {
            stopAfterFailure(
                initialized.recorder,
                newWriter,
                ClientErrorCode.MIC_PERMISSION_REQUIRED,
                "start-recording",
            )
            return RecordingEngineResult.Failure(ClientErrorCode.MIC_PERMISSION_REQUIRED, "start-recording")
        } catch (exception: Exception) {
            stopAfterFailure(initialized.recorder, newWriter, ClientErrorCode.RECORDER_DIED, diagnostic(exception))
            return RecordingEngineResult.Failure(ClientErrorCode.RECORDER_DIED, diagnostic(exception))
        }

        readerThread = Thread(this::readLoop, "aac-recording-reader").apply { start() }
        return RecordingEngineResult.Success(initialized.sourceName)
    }

    @SuppressLint("MissingPermission")
    private fun createRecorder(bufferSize: Int): InitializedRecorder? {
        val candidates =
            listOf(
                CandidateSource(MediaRecorder.AudioSource.VOICE_RECOGNITION, SOURCE_VOICE_RECOGNITION),
                CandidateSource(MediaRecorder.AudioSource.MIC, SOURCE_MIC),
            )

        for (candidate in candidates) {
            val recorder =
                runCatching {
                    AudioRecord(
                        candidate.source,
                        AacLcM4aRecorder.SAMPLE_RATE_HZ,
                        AudioFormat.CHANNEL_IN_MONO,
                        AudioFormat.ENCODING_PCM_16BIT,
                        bufferSize,
                    )
                }.getOrNull()

            if (recorder != null && recorder.state == AudioRecord.STATE_INITIALIZED) {
                sourceName = candidate.sourceName
                return InitializedRecorder(recorder, candidate.sourceName)
            }

            recorder?.release()
        }

        return null
    }

    @SuppressLint("BatteryLife")
    @Suppress("TooGenericExceptionCaught", "SwallowedException", "ReturnCount")
    private fun readLoop() {
        val recorder = audioRecord ?: return
        val targetWriter = writer ?: return
        val buffer = ByteArray(READ_BUFFER_BYTES)

        while (running.get()) {
            val read = recorder.read(buffer, 0, buffer.size)
            if (read < 0) {
                stopAfterFailure(recorder, targetWriter, ClientErrorCode.RECORDER_DIED, "read-$read")
                return
            }
            if (read <= 0) {
                continue
            }

            try {
                targetWriter.write(buffer, 0, read)
            } catch (_: IOException) {
                stopAfterFailure(recorder, targetWriter, ClientErrorCode.STORAGE_FULL, "write")
                return
            } catch (exception: Exception) {
                stopAfterFailure(recorder, targetWriter, ClientErrorCode.ENCODER_FAILED, diagnostic(exception))
                return
            }
        }
    }

    @SuppressLint("BlockingApi")
    @Suppress("TooGenericExceptionCaught", "SwallowedException", "ReturnCount")
    private fun pauseInternal(): RecordingEngineResult {
        if (!running.get()) {
            return failureRef.get() ?: RecordingEngineResult.Success(sourceName)
        }

        running.set(false)

        readerThread?.let { thread ->
            val joined =
                try {
                    thread.join(READER_JOIN_TIMEOUT_MS)
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    false
                }
            if (joined == false && thread.isAlive) {
                return failureOf(ClientErrorCode.RECORDER_DIED, "reader-timeout")
            }
        }

        val failure = failureRef.get()
        if (failure != null) {
            readerThread = null
            return failure
        }

        val targetWriter = writer
        if (targetWriter != null) {
            try {
                if (targetWriter.finish() == null) {
                    targetWriter.releaseSafely()
                    runCatching { targetWriter.outputFile.delete() }
                    return failureOf(ClientErrorCode.SEGMENT_INVALID, "no-aac-output")
                }
            } catch (_: IOException) {
                targetWriter.releaseSafely()
                return failureOf(ClientErrorCode.STORAGE_FULL, "finish")
            } catch (exception: Exception) {
                targetWriter.releaseSafely()
                return failureOf(ClientErrorCode.ENCODER_FAILED, diagnostic(exception))
            }
            targetWriter.releaseSafely()
        }

        val recorder = audioRecord
        if (recorder != null) {
            runCatching { recorder.stop() }
            runCatching { recorder.release() }
        }

        audioRecord = null
        writer = null
        readerThread = null
        return RecordingEngineResult.Success(sourceName)
    }

    private fun stopAfterFailure(
        recorder: AudioRecord,
        targetWriter: StreamingM4aWriter,
        code: ClientErrorCode,
        detail: String,
    ) {
        val failure = RecordingEngineResult.Failure(code, detail)
        failureRef.compareAndSet(null, failure)
        running.set(false)
        runCatching { recorder.stop() }
        runCatching { recorder.release() }
        targetWriter.releaseSafely()
        if (audioRecord === recorder) {
            audioRecord = null
        }
        if (writer === targetWriter) {
            writer = null
        }
    }

    private fun failureOf(
        code: ClientErrorCode,
        detail: String,
    ): RecordingEngineResult.Failure {
        val failure = RecordingEngineResult.Failure(code, detail)
        failureRef.set(failure)
        return failure
    }

    private fun diagnostic(exception: Exception): String =
        "${exception.javaClass.simpleName}:${exception.message}".take(DIAGNOSTIC_DETAIL_LIMIT)

    private data class InitializedRecorder(
        val recorder: AudioRecord,
        val sourceName: String,
    )

    private data class CandidateSource(
        val source: Int,
        val sourceName: String,
    )

    private companion object {
        const val SOURCE_VOICE_RECOGNITION = "VOICE_RECOGNITION"
        const val SOURCE_MIC = "MIC"
        const val MIN_BUFFER_BYTES = 8_192
        const val READ_BUFFER_BYTES = 8_192
        const val READER_JOIN_TIMEOUT_MS = 2_000L
        const val DIAGNOSTIC_DETAIL_LIMIT = 240
    }
}
