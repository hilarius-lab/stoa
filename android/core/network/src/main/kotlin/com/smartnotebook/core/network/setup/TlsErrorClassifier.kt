package com.smartnotebook.core.network.setup

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.cert.CertPathValidatorException
import java.security.cert.CertificateException
import java.security.cert.CertificateExpiredException
import java.security.cert.CertificateNotYetValidException
import javax.net.ssl.SSLException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException

internal object TlsErrorClassifier {
    fun classify(error: Throwable): String {
        val chain = causeChain(error)
        return certificateDetail(chain) ?: transportDetail(chain, error)
    }

    private fun certificateDetail(chain: List<Throwable>): String? =
        when {
            chain.any { it is CertificateExpiredException } -> DETAIL_CERT_EXPIRED
            chain.any { it is CertificateNotYetValidException } -> DETAIL_CERT_NOT_YET_VALID
            chain.any { it is SSLPeerUnverifiedException } -> DETAIL_HOSTNAME_MISMATCH
            chain.any { it is SSLHandshakeException && it.message?.contains(HOSTNAME_NOT_VERIFIED) == true } ->
                DETAIL_HOSTNAME_MISMATCH
            chain.any { it is CertPathValidatorException || it is CertificateException } ->
                DETAIL_CERT_NOT_TRUSTED
            else -> null
        }

    private fun transportDetail(
        chain: List<Throwable>,
        error: Throwable,
    ): String =
        when {
            chain.any { it is UnknownHostException } -> DETAIL_HOST_UNRESOLVABLE
            chain.any { it is SocketTimeoutException } -> DETAIL_TIMED_OUT
            chain.any { it is ConnectException } -> DETAIL_CONNECTION_REFUSED
            chain.any { it is SSLException } -> DETAIL_HANDSHAKE_FAILED
            error is IOException -> error.message ?: DETAIL_IO_FAILED
            else -> DETAIL_UNEXPECTED
        }

    private fun causeChain(error: Throwable): List<Throwable> {
        val chain = mutableListOf<Throwable>()
        var current: Throwable? = error
        while (current != null) {
            if (current !in chain) {
                chain.add(current)
            }
            current = current.cause
        }
        return chain
    }

    private const val HOSTNAME_NOT_VERIFIED = "not verified"
    private const val DETAIL_CERT_EXPIRED = "Server certificate has expired"
    private const val DETAIL_CERT_NOT_YET_VALID = "Server certificate is not yet valid"
    private const val DETAIL_HOSTNAME_MISMATCH = "Hostname does not match the server certificate"
    private const val DETAIL_CERT_NOT_TRUSTED = "Server certificate is not trusted"
    private const val DETAIL_HOST_UNRESOLVABLE = "Host could not be resolved"
    private const val DETAIL_TIMED_OUT = "Connection or TLS handshake timed out"
    private const val DETAIL_CONNECTION_REFUSED = "Connection was refused by the server"
    private const val DETAIL_HANDSHAKE_FAILED = "TLS handshake failed"
    private const val DETAIL_IO_FAILED = "Network connection failed"
    private const val DETAIL_UNEXPECTED = "TLS check failed unexpectedly"
}
