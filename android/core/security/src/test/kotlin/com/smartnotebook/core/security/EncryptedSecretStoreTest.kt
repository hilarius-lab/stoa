package com.smartnotebook.core.security

import com.google.common.truth.Truth.assertThat
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.runBlocking
import org.junit.Test
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

class EncryptedSecretStoreTest {
    private class InMemorySecretBlobSink : SecretBlobSink {
        private val state = MutableStateFlow<Map<String, ByteArray>>(emptyMap())
        val stored: Map<String, ByteArray>
            get() = state.value

        override suspend fun put(
            alias: String,
            blob: ByteArray,
        ) {
            state.update { current -> current + (alias to blob) }
        }

        override suspend fun get(alias: String): ByteArray? = state.value[alias]

        override suspend fun delete(alias: String) {
            state.update { current -> current - alias }
        }

        override suspend fun contains(alias: String): Boolean = state.value.containsKey(alias)
    }

    private fun keyProtector(): KeyProtector {
        val key: SecretKey = KeyGenerator.getInstance("AES").apply { init(KEY_SIZE_BITS) }.generateKey()
        return object : KeyProtector {
            override fun encrypt(plaintext: ByteArray): ByteArray = AesGcmCipher.encrypt(key, plaintext)

            override fun decrypt(payload: ByteArray): ByteArray = AesGcmCipher.decrypt(key, payload)
        }
    }

    private fun storeWith(sink: InMemorySecretBlobSink): EncryptedSecretStore =
        EncryptedSecretStore(keyProtector(), sink)

    @Test
    fun getReturnsStoredValue() =
        runBlocking {
            val store = storeWith(InMemorySecretBlobSink())
            val value = "datenbank-schluessel".toByteArray()

            store.put("db-key", value)

            assertThat(store.get("db-key")).isEqualTo(value)
        }

    @Test
    fun storedBlobDiffersFromPlaintext() =
        runBlocking {
            val sink = InMemorySecretBlobSink()
            val store = storeWith(sink)
            val plaintext = "datenbank-schluessel".toByteArray()

            store.put("db-key", plaintext)

            assertThat(sink.stored.getValue("db-key")).isNotEqualTo(plaintext)
        }

    @Test
    fun getMissingAliasReturnsNull() =
        runBlocking {
            val store = storeWith(InMemorySecretBlobSink())

            assertThat(store.get("missing")).isNull()
        }

    @Test
    fun deleteRemovesSecret() =
        runBlocking {
            val store = storeWith(InMemorySecretBlobSink())

            store.put("file-key", "wert".toByteArray())
            store.delete("file-key")

            assertThat(store.get("file-key")).isNull()
            assertThat(store.contains("file-key")).isFalse()
        }

    @Test
    fun containsReflectsState() =
        runBlocking {
            val store = storeWith(InMemorySecretBlobSink())

            assertThat(store.contains("alias")).isFalse()
            store.put("alias", "wert".toByteArray())
            assertThat(store.contains("alias")).isTrue()
        }

    @Test
    fun getReturnsNullForCorruptedBlob() =
        runBlocking {
            val sink = InMemorySecretBlobSink()
            val store = storeWith(sink)

            sink.put("db-key", ByteArray(CORRUPTED_BLOB_BYTES) { index -> index.toByte() })

            assertThat(store.get("db-key")).isNull()
        }

    private companion object {
        private const val KEY_SIZE_BITS = 256
        private const val CORRUPTED_BLOB_BYTES = 64
    }
}
