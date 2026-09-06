package com.smartnotebook.core.security

public interface KeyProtector {
    public fun encrypt(plaintext: ByteArray): ByteArray

    public fun decrypt(payload: ByteArray): ByteArray
}
