package com.smartnotebook.core.security

public class EncryptedSecretStore(
    private val keyProtector: KeyProtector,
    private val sink: SecretBlobSink,
) : SecretStore {
    override suspend fun put(
        alias: String,
        value: ByteArray,
    ) {
        sink.put(alias, keyProtector.encrypt(value))
    }

    override suspend fun get(alias: String): ByteArray? {
        val blob = sink.get(alias) ?: return null
        @Suppress("SwallowedException", "TooGenericExceptionCaught")
        return try {
            keyProtector.decrypt(blob)
        } catch (_: Exception) {
            null
        }
    }

    override suspend fun delete(alias: String) {
        sink.delete(alias)
    }

    override suspend fun contains(alias: String): Boolean = sink.contains(alias)
}
