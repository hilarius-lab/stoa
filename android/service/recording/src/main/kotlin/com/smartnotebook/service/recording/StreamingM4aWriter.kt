package com.smartnotebook.service.recording

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import java.io.File
import java.io.IOException

internal class StreamingM4aWriter(
    val outputFile: File,
) {
    private var encoder: MediaCodec? = null
    private var muxer: MediaMuxer? = null
    private var trackIndex = -1
    private var started = false
    private var stopped = false
    private var inputOffsetBytes = 0L

    @Suppress("TooGenericExceptionCaught")
    fun start() {
        outputFile.parentFile?.mkdirs()
        val newEncoder = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
        try {
            val newMuxer = MediaMuxer(outputFile.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
            newEncoder.configure(createEncoderFormat(), null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            newEncoder.start()
            encoder = newEncoder
            muxer = newMuxer
        } catch (exception: Exception) {
            runCatching { newEncoder.release() }
            throw exception
        }
    }

    @Throws(IOException::class)
    fun write(
        pcm: ByteArray,
        offset: Int,
        size: Int,
    ) {
        val targetEncoder = encoder ?: return
        var currentOffset = offset
        var remaining = size

        while (remaining > 0) {
            val chunkSize = minOf(MAX_INPUT_CHUNK_BYTES, remaining)
            val queued = queueInput(targetEncoder, pcm, currentOffset, chunkSize, false)
            if (queued <= 0) {
                drainOutput(targetEncoder)
                continue
            }

            inputOffsetBytes += queued.toLong()
            currentOffset += queued
            remaining -= queued
            drainOutput(targetEncoder)
        }
    }

    @Throws(IOException::class)
    @Suppress("ReturnCount")
    fun finish(): M4aSegmentMetadata? {
        val targetEncoder = encoder ?: return null
        val targetMuxer = muxer ?: return null

        queueInput(targetEncoder, ByteArray(0), 0, 0, true)

        var attempts = 0
        var sawEndOfStream = false
        while (!sawEndOfStream) {
            sawEndOfStream = drainOutput(targetEncoder)
            attempts++
            if (attempts >= MAX_EOS_DRAIN_ATTEMPTS) {
                error("encoder-eos-timeout")
            }
        }

        if (!started) {
            runCatching { targetMuxer.release() }
            encoder = null
            muxer = null
            return null
        }

        targetMuxer.stop()
        stopped = true
        return M4aSegmentValidator.validate(outputFile)
    }

    fun releaseSafely() {
        runCatching { encoder?.stop() }
        runCatching { encoder?.release() }
        runCatching {
            if (started && !stopped) {
                muxer?.stop()
            }
        }
        runCatching { muxer?.release() }
        encoder = null
        muxer = null
    }

    private fun createEncoderFormat(): MediaFormat {
        val format = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, SAMPLE_RATE_HZ, CHANNEL_COUNT)
        format.setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
        format.setInteger(MediaFormat.KEY_BIT_RATE, BIT_RATE_BPS)
        return format
    }

    private fun queueInput(
        targetEncoder: MediaCodec,
        pcm: ByteArray,
        offset: Int,
        size: Int,
        endOfStream: Boolean,
    ): Int {
        val index = targetEncoder.dequeueInputBuffer(INPUT_TIMEOUT_US)
        check(index >= 0) { "encoder-input-unavailable" }
        val buffer = checkNotNull(targetEncoder.getInputBuffer(index)) { "encoder-input-buffer-missing" }

        val actualSize = if (size == 0) 0 else minOf(size, buffer.remaining())
        if (actualSize > 0) {
            buffer.put(pcm, offset, actualSize)
        }

        val ptsUs = (inputOffsetBytes / BYTES_PER_PCM_SAMPLE) * MICROS_PER_SECOND / SAMPLE_RATE_HZ
        val flags = if (endOfStream) MediaCodec.BUFFER_FLAG_END_OF_STREAM else 0
        targetEncoder.queueInputBuffer(index, 0, actualSize, ptsUs, flags)
        return actualSize
    }

    @Throws(IOException::class)
    private fun drainOutput(targetEncoder: MediaCodec): Boolean {
        val info = MediaCodec.BufferInfo()
        var endOfStream = false
        var active = true

        while (active) {
            val index = targetEncoder.dequeueOutputBuffer(info, DRAIN_TIMEOUT_US)
            when {
                index == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    val targetMuxer = muxer ?: error("muxer-missing")
                    trackIndex = targetMuxer.addTrack(targetEncoder.outputFormat)
                    targetMuxer.start()
                    started = true
                }

                index >= 0 -> {
                    val buffer = checkNotNull(targetEncoder.getOutputBuffer(index)) { "encoder-output-buffer-missing" }
                    val size = info.size
                    if (size > 0 && (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG) == 0) {
                        val targetMuxer = muxer ?: error("muxer-missing")
                        check(trackIndex >= 0) { "muxer-track-missing" }
                        buffer.position(info.offset)
                        buffer.limit(info.offset + size)
                        targetMuxer.writeSampleData(trackIndex, buffer, info)
                    }
                    targetEncoder.releaseOutputBuffer(index, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                        endOfStream = true
                        active = false
                    }
                }

                index == MediaCodec.INFO_TRY_AGAIN_LATER -> active = false
                else -> error("encoder-output-status-$index")
            }
        }

        return endOfStream
    }

    private companion object {
        const val SAMPLE_RATE_HZ = AacLcM4aRecorder.SAMPLE_RATE_HZ
        const val CHANNEL_COUNT = AacLcM4aRecorder.CHANNEL_COUNT
        const val BIT_RATE_BPS = AacLcM4aRecorder.BIT_RATE_BPS
        const val BYTES_PER_PCM_SAMPLE = 2L
        const val MICROS_PER_SECOND = 1_000_000L
        const val MAX_INPUT_CHUNK_BYTES = 65_536
        const val INPUT_TIMEOUT_US = 100_000L
        const val DRAIN_TIMEOUT_US = 10_000L
        const val MAX_EOS_DRAIN_ATTEMPTS = 1_000
    }
}
