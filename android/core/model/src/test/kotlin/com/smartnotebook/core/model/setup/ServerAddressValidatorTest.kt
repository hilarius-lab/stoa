package com.smartnotebook.core.model.setup

import com.google.common.truth.Truth.assertThat
import org.junit.Test

class ServerAddressValidatorTest {
    @Test
    fun validHttpsInputAppliesDefaults() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", ""))

        assertThat(result.isValid).isTrue()
        val address = checkNotNull(result.address)
        assertThat(address.scheme).isEqualTo(HTTPS_SCHEME)
        assertThat(address.host).isEqualTo(EXAMPLE_HOST)
        assertThat(address.port).isEqualTo(HTTPS_DEFAULT_PORT)
        assertThat(address.basePath).isEqualTo(DEFAULT_BASE_PATH)
        assertThat(address.isCleartext).isFalse()
    }

    @Test
    fun schemeIsNormalizedToLowerCase() {
        val result = ServerAddressValidator.validate(input(UPPERCASE_HTTPS_SCHEME, EXAMPLE_HOST, "", ""))

        assertThat(checkNotNull(result.address).scheme).isEqualTo(HTTPS_SCHEME)
    }

    @Test
    fun httpInputIsCleartextWithDefaultPort() {
        val result = ServerAddressValidator.validate(input(HTTP_SCHEME, EXAMPLE_HOST, "", ""))

        val address = checkNotNull(result.address)
        assertThat(address.isCleartext).isTrue()
        assertThat(address.port).isEqualTo(HTTP_DEFAULT_PORT)
    }

    @Test
    fun unsupportedSchemeIsRejected() {
        val result = ServerAddressValidator.validate(input(UNSUPPORTED_SCHEME, EXAMPLE_HOST, "", ""))

        assertThat(result.isValid).isFalse()
        assertThat(result.address).isNull()
        assertThat(result.errors).containsExactly(ServerAddressError.SCHEME)
    }

    @Test
    fun hostWithSchemePrefixIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, "https://$EXAMPLE_HOST", "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun hostWithPortSuffixIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, "$EXAMPLE_HOST:$CUSTOM_PORT", "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun hostWithWhitespaceIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, "exam ple.com", "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun hostWithPathIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, "$EXAMPLE_HOST/", "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun hostnameIsLowerCased() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, "Example.COM", "", ""))

        assertThat(checkNotNull(result.address).host).isEqualTo(EXAMPLE_HOST)
    }

    @Test
    fun hostnameWithTrailingHyphenInLabelIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, "example-.com", "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun validIpv4AddressIsAccepted() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, IPV4_ADDRESS, "", ""))

        assertThat(checkNotNull(result.address).host).isEqualTo(IPV4_ADDRESS)
    }

    @Test
    fun ipv4OctetAboveMaxIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, IPV4_OCTET_ABOVE_MAX, "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun ipv4WithLeadingZeroIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, IPV4_LEADING_ZERO, "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun ipv4WithWrongOctetCountIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, IPV4_TOO_FEW_OCTETS, "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun bareIpv6IsWrappedInBrackets() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, BARE_IPV6, "", ""))

        assertThat(checkNotNull(result.address).host).isEqualTo(BRACKETED_LOOPBACK_IPV6)
    }

    @Test
    fun bracketedIpv6KeepsBrackets() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, BRACKETED_IPV6, "", ""))

        assertThat(checkNotNull(result.address).host).isEqualTo(BRACKETED_IPV6)
    }

    @Test
    fun ipv6WithTooManyGroupsIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, IPV6_TOO_MANY_GROUPS, "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun ipv6WithNonHexGroupIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, IPV6_NON_HEX_GROUP, "", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.HOST)
    }

    @Test
    fun explicitPortIsAccepted() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, CUSTOM_PORT, ""))

        assertThat(checkNotNull(result.address).port).isEqualTo(CUSTOM_PORT_VALUE)
    }

    @Test
    fun portZeroIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "0", ""))

        assertThat(result.errors).containsExactly(ServerAddressError.PORT)
    }

    @Test
    fun portAboveMaxIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, PORT_ABOVE_MAX, ""))

        assertThat(result.errors).containsExactly(ServerAddressError.PORT)
    }

    @Test
    fun portWithLeadingZeroIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, PORT_LEADING_ZERO, ""))

        assertThat(result.errors).containsExactly(ServerAddressError.PORT)
    }

    @Test
    fun portWithLettersIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, PORT_WITH_LETTERS, ""))

        assertThat(result.errors).containsExactly(ServerAddressError.PORT)
    }

    @Test
    fun explicitBasePathIsKept() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "/api/v1"))

        assertThat(checkNotNull(result.address).basePath).isEqualTo("/api/v1")
    }

    @Test
    fun basePathWithoutLeadingSlashGetsOne() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "api/v1"))

        assertThat(checkNotNull(result.address).basePath).isEqualTo("/api/v1")
    }

    @Test
    fun basePathWithTrailingSlashIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "api/"))

        assertThat(result.errors).containsExactly(ServerAddressError.BASE_PATH)
    }

    @Test
    fun basePathWithDoubleSlashIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "api//v1"))

        assertThat(result.errors).containsExactly(ServerAddressError.BASE_PATH)
    }

    @Test
    fun basePathWithQueryIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "/api?x=1"))

        assertThat(result.errors).containsExactly(ServerAddressError.BASE_PATH)
    }

    @Test
    fun basePathWithFragmentIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "/api#sync"))

        assertThat(result.errors).containsExactly(ServerAddressError.BASE_PATH)
    }

    @Test
    fun basePathWithBackslashIsRejected() {
        val result = ServerAddressValidator.validate(input(HTTPS_SCHEME, EXAMPLE_HOST, "", "api\\v1"))

        assertThat(result.errors).containsExactly(ServerAddressError.BASE_PATH)
    }

    @Test
    fun multipleErrorsAreCollected() {
        val result = ServerAddressValidator.validate(input(UNSUPPORTED_SCHEME, "bad host", "0", ""))

        assertThat(result.isValid).isFalse()
        assertThat(result.errors)
            .containsExactly(
                ServerAddressError.SCHEME,
                ServerAddressError.HOST,
                ServerAddressError.PORT,
            )
    }

    private fun input(
        scheme: String,
        host: String,
        port: String,
        basePath: String,
    ): ServerAddressInput = ServerAddressInput(scheme = scheme, host = host, port = port, basePath = basePath)

    private companion object {
        private const val HTTPS_SCHEME = "https"
        private const val HTTP_SCHEME = "http"
        private const val UPPERCASE_HTTPS_SCHEME = "HTTPS"
        private const val UNSUPPORTED_SCHEME = "ftp"
        private const val EXAMPLE_HOST = "example.com"
        private const val IPV4_ADDRESS = "192.168.1.10"
        private const val IPV4_OCTET_ABOVE_MAX = "256.1.1.1"
        private const val IPV4_LEADING_ZERO = "192.168.001.1"
        private const val IPV4_TOO_FEW_OCTETS = "192.168.1"
        private const val BARE_IPV6 = "::1"
        private const val BRACKETED_LOOPBACK_IPV6 = "[::1]"
        private const val BRACKETED_IPV6 = "[fe80::1]"
        private const val IPV6_TOO_MANY_GROUPS = "1:2:3:4:5:6:7:8:9"
        private const val IPV6_NON_HEX_GROUP = "gggg::1"
        private const val CUSTOM_PORT = "8443"
        private const val CUSTOM_PORT_VALUE = 8443
        private const val PORT_ABOVE_MAX = "65536"
        private const val PORT_LEADING_ZERO = "0443"
        private const val PORT_WITH_LETTERS = "80a"
        private const val HTTPS_DEFAULT_PORT = 443
        private const val HTTP_DEFAULT_PORT = 80
        private const val DEFAULT_BASE_PATH = "/api"
    }
}
