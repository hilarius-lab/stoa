package com.smartnotebook.core.security

public interface SecretBlobSink {
    public suspend fun put(
        alias: String,
        blob: ByteArray,
    )

    public suspend fun get(alias: String): ByteArray?

    public suspend fun delete(alias: String)

    public suspend fun contains(alias: String): Boolean
}
