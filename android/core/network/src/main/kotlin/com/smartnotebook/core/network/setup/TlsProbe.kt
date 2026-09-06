package com.smartnotebook.core.network.setup

import com.smartnotebook.core.model.ClientPreferences
import com.smartnotebook.core.model.ServerProfile
import com.smartnotebook.core.model.setup.ProbeOutcome
import com.smartnotebook.core.model.setup.WizardTlsProbe
import okhttp3.OkHttpClient
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import javax.net.ssl.SSLSocket

public class TlsProbe(
    private val allowCleartext: Boolean,
    private val clientFactory: () -> OkHttpClient = ::defaultClient,
) : WizardTlsProbe {
    override suspend fun run(
        profile: ServerProfile,
        preferences: ClientPreferences,
    ): ProbeOutcome =
        when (profile.scheme.trim().lowercase()) {
            SCHEME_HTTP -> cleartextOutcome()
            SCHEME_HTTPS -> performHandshake(profile)
            else -> ProbeOutcome.Failed(DETAIL_UNSUPPORTED_SCHEME)
        }

    private fun cleartextOutcome(): ProbeOutcome =
        if (allowCleartext) {
            ProbeOutcome.Passed
        } else {
            ProbeOutcome.Blocked(DETAIL_CLEARTEXT_BLOCKED)
        }

    private fun performHandshake(profile: ServerProfile): ProbeOutcome {
        val socket =
            try {
                openVerifiedSocket(clientFactory(), profile)
            } catch (error: IOException) {
                return ProbeOutcome.Failed(TlsErrorClassifier.classify(error))
            }
        runCatching { socket.close() }
        return ProbeOutcome.Passed
    }

    private fun openVerifiedSocket(
        client: OkHttpClient,
        profile: ServerProfile,
    ): SSLSocket {
        val host = hostForLookup(profile.host)
        val plain = Socket()
        try {
            plain.connect(
                InetSocketAddress(host, profile.port),
                timeoutMillis(profile.connectionTimeoutMillis),
            )
            val verified = client.sslSocketFactory.createSocket(plain, host, profile.port, true) as SSLSocket
            verified.setSoTimeout(timeoutMillis(profile.requestTimeoutMillis))
            val parameters = verified.sslParameters
            parameters.endpointIdentificationAlgorithm = ENDPOINT_IDENTIFICATION_HTTPS
            verified.sslParameters = parameters
            verified.startHandshake()
            return verified
        } catch (error: IOException) {
            runCatching { plain.close() }
            throw error
        }
    }

    private fun hostForLookup(host: String): String =
        if (host.startsWith(IPV6_OPEN_BRACKET)) {
            host.removeSurrounding(IPV6_OPEN_BRACKET, IPV6_CLOSE_BRACKET)
        } else {
            host
        }

    private fun timeoutMillis(millis: Long): Int = millis.coerceAtMost(MAX_SOCKET_TIMEOUT_MILLIS.toLong()).toInt()

    public companion object {
        public fun defaultClient(): OkHttpClient = OkHttpClient.Builder().build()

        private const val SCHEME_HTTP = "http"
        private const val SCHEME_HTTPS = "https"
        private const val IPV6_OPEN_BRACKET = "["
        private const val IPV6_CLOSE_BRACKET = "]"
        private const val ENDPOINT_IDENTIFICATION_HTTPS = "HTTPS"
        private const val MAX_SOCKET_TIMEOUT_MILLIS = Int.MAX_VALUE
        private const val DETAIL_CLEARTEXT_BLOCKED = "Cleartext HTTP is not permitted for this build"
        private const val DETAIL_UNSUPPORTED_SCHEME = "Unsupported server scheme; only http and https are valid"
    }
}
