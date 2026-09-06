package com.smartnotebook.core.network.setup

import com.google.common.truth.Truth.assertThat
import com.smartnotebook.core.model.ClientPreferences
import com.smartnotebook.core.model.ServerProfile
import com.smartnotebook.core.model.setup.ProbeOutcome
import kotlinx.coroutines.runBlocking
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.KeyStore
import java.security.cert.CertPathValidatorException
import java.security.cert.CertificateException
import java.security.cert.CertificateExpiredException
import java.security.cert.CertificateNotYetValidException
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

class TlsProbeTest {
    private val servers = mutableListOf<MockWebServer>()
    private val preferences = ClientPreferences()

    @After
    fun closeServers() {
        servers.forEach { it.close() }
        servers.clear()
    }

    @Test
    fun selfSignedCertificateIsReportedAsNotTrusted() {
        val port = startTlsServer()
        val outcome = runBlocking { TlsProbe(allowCleartext = true).run(httpsProfile(port), preferences) }
        assertThat(outcome).isInstanceOf(ProbeOutcome.Failed::class.java)
        assertThat((outcome as ProbeOutcome.Failed).detail).isEqualTo("Server certificate is not trusted")
    }

    @Test
    fun handshakePassesWhenCertificateIsTrusted() {
        val port = startTlsServer()
        val probe = TlsProbe(allowCleartext = true, clientFactory = { trustingClient() })
        val outcome = runBlocking { probe.run(httpsProfile(port), preferences) }
        assertThat(outcome).isEqualTo(ProbeOutcome.Passed)
    }

    @Test
    fun cleartextProfilePassesWhenCleartextIsAllowed() {
        val probe = TlsProbe(allowCleartext = true)
        val outcome = runBlocking { probe.run(profile(scheme = "http", host = "localhost", port = 8080), preferences) }
        assertThat(outcome).isEqualTo(ProbeOutcome.Passed)
    }

    @Test
    fun cleartextProfileIsBlockedWhenCleartextIsDisallowed() {
        val probe = TlsProbe(allowCleartext = false)
        val outcome = runBlocking { probe.run(profile(scheme = "http", host = "localhost", port = 8080), preferences) }
        assertThat(outcome).isInstanceOf(ProbeOutcome.Blocked::class.java)
        assertThat((outcome as ProbeOutcome.Blocked).detail)
            .isEqualTo("Cleartext HTTP is not permitted for this build")
    }

    @Test
    fun unsupportedSchemeIsReported() {
        val probe = TlsProbe(allowCleartext = true)
        val outcome = runBlocking { probe.run(profile(scheme = "ftp", host = "localhost", port = 21), preferences) }
        assertThat(outcome).isInstanceOf(ProbeOutcome.Failed::class.java)
        assertThat((outcome as ProbeOutcome.Failed).detail)
            .isEqualTo("Unsupported server scheme; only http and https are valid")
    }

    @Test
    fun refusedConnectionIsReportedClearly() {
        val port = freePort()
        val probe = TlsProbe(allowCleartext = true)
        val outcome = runBlocking { probe.run(httpsProfile(port), preferences) }
        assertThat(outcome).isInstanceOf(ProbeOutcome.Failed::class.java)
        assertThat((outcome as ProbeOutcome.Failed).detail).isEqualTo("Connection was refused by the server")
    }

    @Test
    fun unresolvableHostIsReportedClearly() {
        val probe = TlsProbe(allowCleartext = true)
        val hostProfile = profile(scheme = "https", host = "no-such-host.invalid", port = 443)
        val outcome = runBlocking { probe.run(hostProfile, preferences) }
        assertThat(outcome).isInstanceOf(ProbeOutcome.Failed::class.java)
        assertThat((outcome as ProbeOutcome.Failed).detail).isEqualTo("Host could not be resolved")
    }

    @Test
    fun classifierMapsCertificateExpired() {
        val cause = CertificateExpiredException("certificate expired")
        val error = withCause(SSLHandshakeException("handshake failed"), cause)
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Server certificate has expired")
    }

    @Test
    fun classifierMapsCertificateNotYetValid() {
        val cause = CertificateNotYetValidException("certificate not yet valid")
        val error = withCause(SSLHandshakeException("handshake failed"), cause)
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Server certificate is not yet valid")
    }

    @Test
    fun classifierMapsUnverifiedPeer() {
        val error = SSLPeerUnverifiedException("Hostname localhost not verified")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Hostname does not match the server certificate")
    }

    @Test
    fun classifierMapsHostnameMismatchMessage() {
        val error = SSLHandshakeException("Hostname localhost not verified")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Hostname does not match the server certificate")
    }

    @Test
    fun classifierMapsUntrustedCertificatePath() {
        val cause = CertPathValidatorException("PKIX path building failed")
        val error = withCause(SSLHandshakeException("handshake failed"), cause)
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Server certificate is not trusted")
    }

    @Test
    fun classifierMapsGenericCertificateException() {
        val error = SSLException(CertificateException("unable to process certificate"))
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Server certificate is not trusted")
    }

    @Test
    fun classifierMapsUnknownHost() {
        val error = UnknownHostException("no-such-host.invalid")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Host could not be resolved")
    }

    @Test
    fun classifierMapsTimeout() {
        val error = SocketTimeoutException("Connect timed out")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Connection or TLS handshake timed out")
    }

    @Test
    fun classifierMapsRefusedConnection() {
        val error = ConnectException("Connection refused")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("Connection was refused by the server")
    }

    @Test
    fun classifierMapsGenericSslError() {
        val error = SSLException("Unrecognized SSL message")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("TLS handshake failed")
    }

    @Test
    fun classifierMapsGenericIoError() {
        val error = IOException("boom")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("boom")
    }

    @Test
    fun classifierMapsUnexpectedError() {
        val error = IllegalStateException("unexpected")
        assertThat(TlsErrorClassifier.classify(error)).isEqualTo("TLS check failed unexpectedly")
    }

    private fun withCause(
        error: Throwable,
        cause: Throwable,
    ): Throwable = error.apply { initCause(cause) }

    private fun httpsProfile(port: Int): ServerProfile = profile(scheme = "https", host = "localhost", port = port)

    private fun profile(
        scheme: String,
        host: String,
        port: Int,
    ): ServerProfile =
        ServerProfile(
            name = "Test",
            scheme = scheme,
            host = host,
            port = port,
            basePath = "/api",
            requestTimeoutMillis = 5_000,
            connectionTimeoutMillis = 5_000,
        )

    private fun startTlsServer(): Int {
        val server = MockWebServer()
        server.useHttps(serverSocketFactory())
        server.start()
        servers.add(server)
        return server.port
    }

    private fun freePort(): Int = ServerSocket(0).use { it.localPort }

    private fun serverSocketFactory(): SSLSocketFactory {
        val keyManagerFactory = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
        keyManagerFactory.init(loadKeyStore(), KEYSTORE_PASSWORD.toCharArray())
        val context = SSLContext.getInstance("TLS")
        context.init(keyManagerFactory.keyManagers, null, null)
        return context.socketFactory
    }

    private fun trustingClient(): OkHttpClient {
        val trustedStore = KeyStore.getInstance("PKCS12")
        trustedStore.load(null, null)
        val source = loadKeyStore()
        val alias = source.aliases().nextElement()
        trustedStore.setCertificateEntry("trusted", source.getCertificate(alias))
        val trustManagerFactory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        trustManagerFactory.init(trustedStore)
        val trustManager = trustManagerFactory.trustManagers.first { it is X509TrustManager } as X509TrustManager
        val context = SSLContext.getInstance("TLS")
        context.init(null, arrayOf(trustManager), null)
        return OkHttpClient.Builder().sslSocketFactory(context.socketFactory, trustManager).build()
    }

    private fun loadKeyStore(): KeyStore {
        val stream =
            javaClass.classLoader?.getResourceAsStream(KEYSTORE_RESOURCE)
                ?: error("Missing test fixture $KEYSTORE_RESOURCE")
        val keyStore = KeyStore.getInstance("PKCS12")
        stream.use { keyStore.load(it, KEYSTORE_PASSWORD.toCharArray()) }
        return keyStore
    }

    private companion object {
        private const val KEYSTORE_RESOURCE = "tls-test/test-localhost.p12"
        private const val KEYSTORE_PASSWORD = "changeit"
    }
}
