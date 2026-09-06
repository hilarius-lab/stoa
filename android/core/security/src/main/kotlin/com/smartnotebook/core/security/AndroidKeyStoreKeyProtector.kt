package com.smartnotebook.core.security

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey

public class AndroidKeyStoreKeyProtector : KeyProtector {
    private val masterKey: SecretKey = loadOrCreateMasterKey()

    override fun encrypt(plaintext: ByteArray): ByteArray = AesGcmCipher.encrypt(masterKey, plaintext)

    override fun decrypt(payload: ByteArray): ByteArray = AesGcmCipher.decrypt(masterKey, payload)

    private fun loadOrCreateMasterKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        keyStore.getEntry(KEY_ALIAS, null)?.let { entry ->
            if (entry is KeyStore.SecretKeyEntry) {
                return entry.secretKey
            }
        }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER)
        generator.init(
            KeyGenParameterSpec
                .Builder(
                    KEY_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(KEY_SIZE_BITS)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
        private const val KEY_ALIAS = "com.smartnotebook.master.v1"
        private const val KEY_SIZE_BITS = 256
    }
}
