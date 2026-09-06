package com.smartnotebook.service.recording

import android.media.MediaExtractor
import android.media.MediaFormat
import android.media.MediaMetadataRetriever
import java.io.File
import java.nio.ByteBuffer
import java.security.MessageDigest

public data class M4aSegmentMetadata(
    public val fileBytes: Long,
    public val mimeType: String,
    public val sampleRateHz: Int,
    public val channelCount: Int,
    public val bitRateBps: Int,
    public val durationMs: Long,
    public val isAacLc: Boolean,
)

private const val MICROS_PER_MILLIS: Long = 1_000L
private const val MICROS_PER_SECOND: Long = 1_000_000L
private const val BITS_PER_BYTE: Double = 8.0
private const val NON_POSITIVE: Double = 0.0
private const val HASH_BUFFER_BYTES: Int = 8_192
private const val FIRST_BYTE_MASK: Int = 0xFF
private const val OBJECT_TYPE_SHIFT: Int = 3

public object M4aSegmentValidator {
    private const val AAC_OBJECT_TYPE_LC: Int = 2
    private const val CSD0_KEY: String = "csd-0"

    @Suppress("ReturnCount", "TooGenericExceptionCaught", "SwallowedException")
    public fun validate(file: File): M4aSegmentMetadata? {
        if (!file.exists() || file.length() <= 0L) {
            return null
        }

        val extractor = MediaExtractor()
        try {
            extractor.setDataSource(file.absolutePath)
            if (extractor.trackCount == 0) {
                return null
            }

            val trackIndex = 0
            extractor.selectTrack(trackIndex)
            val format = extractor.getTrackFormat(trackIndex)
            val mimeType = format.getString(MediaFormat.KEY_MIME) ?: return null
            if (mimeType != MediaFormat.MIMETYPE_AUDIO_AAC) {
                return null
            }

            val sampleRateHz = format.getIntegerOrNull(MediaFormat.KEY_SAMPLE_RATE) ?: return null
            val channelCount = format.getIntegerOrNull(MediaFormat.KEY_CHANNEL_COUNT) ?: return null
            val durationUs = metadataDurationUs(file)
            if (durationUs == null || durationUs <= 0L) {
                return null
            }

            val bitRateBps =
                format.getIntegerOrNull(MediaFormat.KEY_BIT_RATE)
                    ?: estimatedBitRateBps(file.length(), durationUs)
            if (bitRateBps <= 0) {
                return null
            }

            return M4aSegmentMetadata(
                fileBytes = file.length(),
                mimeType = mimeType,
                sampleRateHz = sampleRateHz,
                channelCount = channelCount,
                bitRateBps = bitRateBps,
                durationMs = durationUs / MICROS_PER_MILLIS,
                isAacLc = isAacLc(format),
            )
        } catch (_: Exception) {
            return null
        } finally {
            extractor.release()
        }
    }

    private fun isAacLc(format: MediaFormat): Boolean {
        val csd0 = format.csd0Buffer() ?: return false
        val bytes = ByteArray(csd0.remaining())
        csd0.get(bytes)
        return bytes.isNotEmpty() &&
            ((bytes[0].toInt() and FIRST_BYTE_MASK) ushr OBJECT_TYPE_SHIFT) == AAC_OBJECT_TYPE_LC
    }

    private fun estimatedBitRateBps(
        fileBytes: Long,
        durationUs: Long,
    ): Int {
        val durationSeconds = durationUs.toDouble() / MICROS_PER_SECOND
        if (durationSeconds <= NON_POSITIVE) {
            return 0
        }
        return ((fileBytes.toDouble() * BITS_PER_BYTE) / durationSeconds).toInt()
    }

    @Suppress("ReturnCount", "TooGenericExceptionCaught", "SwallowedException")
    private fun metadataDurationUs(file: File): Long? {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(file.absolutePath)
            val durationMs =
                retriever
                    .extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)
                    ?.toLongOrNull()
            return durationMs?.takeIf { it > 0L }?.times(MICROS_PER_MILLIS)
        } catch (_: Exception) {
            return null
        } finally {
            retriever.release()
        }
    }

    @Suppress("TooGenericExceptionCaught", "SwallowedException")
    private fun MediaFormat.getIntegerOrNull(key: String): Int? = runCatching { getInteger(key) }.getOrNull()

    @Suppress("TooGenericExceptionCaught", "SwallowedException")
    private fun MediaFormat.csd0Buffer(): ByteBuffer? = runCatching { getByteBuffer(CSD0_KEY) }.getOrNull()
}

public fun sha256Hex(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buffer = ByteArray(HASH_BUFFER_BYTES)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) {
                break
            }
            digest.update(buffer, 0, read)
        }
    }
    return digest.digest().joinToString("") { byte -> "%02x".format(byte) }
}
