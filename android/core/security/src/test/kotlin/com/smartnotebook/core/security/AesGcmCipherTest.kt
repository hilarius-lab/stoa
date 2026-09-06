package com.smartnotebook.core.security

import com.google.common.truth.Truth.assertThat
import org.junit.Assert.assertThrows
import org.junit.Test
import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class AesGcmCipherTest {
    private fun newKey(): SecretKey = KeyGenerator.getInstance("AES").apply { init(KEY_SIZE_BITS) }.generateKey()

    @Test
    fun decryptReturnsPlaintextAfterEncrypt() {
        val key = newKey()
        val plaintext = "geheimer-wert".toByteArray()

        val payload = AesGcmCipher.encrypt(key, plaintext)

        assertThat(AesGcmCipher.decrypt(key, payload)).isEqualTo(plaintext)
    }

    @Test
    fun roundTripSupportsEmptyPlaintext() {
        val key = newKey()

        val payload = AesGcmCipher.encrypt(key, ByteArray(0))

        assertThat(AesGcmCipher.decrypt(key, payload)).isEmpty()
    }

    @Test
    fun encryptUsesFreshNoncePerCall() {
        val key = newKey()
        val plaintext = "gleicher-wert".toByteArray()

        val first = AesGcmCipher.encrypt(key, plaintext)
        val second = AesGcmCipher.encrypt(key, plaintext)

        assertThat(first).isNotEqualTo(second)
        assertThat(AesGcmCipher.decrypt(key, first)).isEqualTo(plaintext)
        assertThat(AesGcmCipher.decrypt(key, second)).isEqualTo(plaintext)
    }

    @Test
    fun payloadContainsNonceAndAuthenticationTag() {
        val key = newKey()
        val plaintext = "wert".toByteArray()

        val payload = AesGcmCipher.encrypt(key, plaintext)

        assertThat(payload).hasLength(plaintext.size + NONCE_BYTES + TAG_BYTES)
    }

    @Test
    fun decryptRejectsTamperedPayload() {
        val key = newKey()
        val payload = AesGcmCipher.encrypt(key, "wert".toByteArray())
        payload[payload.size - 1] = if (payload[payload.size - 1] == 0.toByte()) 1.toByte() else 0.toByte()

        assertThrows(AEADBadTagException::class.java) {
            AesGcmCipher.decrypt(key, payload)
        }
    }

    @Test
    fun decryptRejectsWrongKey() {
        val payload = AesGcmCipher.encrypt(newKey(), "wert".toByteArray())

        assertThrows(AEADBadTagException::class.java) {
            AesGcmCipher.decrypt(newKey(), payload)
        }
    }

    @Test
    fun decryptRejectsMalformedPayload() {
        assertThrows(IllegalArgumentException::class.java) {
            AesGcmCipher.decrypt(newKey(), ByteArray(NONCE_BYTES))
        }
    }

    private companion object {
        private const val KEY_SIZE_BITS = 256
        private const val NONCE_BYTES = 12
        private const val TAG_BYTES = 16
    }
}
