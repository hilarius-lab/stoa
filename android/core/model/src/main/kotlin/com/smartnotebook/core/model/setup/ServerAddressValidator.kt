package com.smartnotebook.core.model.setup

public object ServerAddressValidator {
    public fun validate(input: ServerAddressInput): ServerAddressValidation {
        val errors = mutableSetOf<ServerAddressError>()
        val scheme = input.scheme.trim().lowercase()
        if (scheme !in SUPPORTED_SCHEMES) {
            errors += ServerAddressError.SCHEME
        }
        val host = normalizeHost(input.host, errors)
        val port = normalizePort(input.port, scheme, errors)
        val basePath = normalizeBasePath(input.basePath, errors)
        if (errors.isNotEmpty()) {
            return ServerAddressValidation(address = null, errors = errors)
        }
        return ServerAddressValidation(
            address =
                ValidatedServerAddress(
                    scheme = scheme,
                    host = checkNotNull(host),
                    port = checkNotNull(port),
                    basePath = checkNotNull(basePath),
                ),
            errors = emptySet(),
        )
    }

    private fun normalizeHost(
        raw: String,
        errors: MutableSet<ServerAddressError>,
    ): String? {
        val normalized = HostRules.normalizedHost(raw.trim())
        if (normalized == null) {
            errors += ServerAddressError.HOST
        }
        return normalized
    }

    private fun normalizePort(
        raw: String,
        scheme: String,
        errors: MutableSet<ServerAddressError>,
    ): Int? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) {
            return defaultPort(scheme)
        }
        val port = parsePort(trimmed)
        if (port == null) {
            errors += ServerAddressError.PORT
        }
        return port
    }

    private fun parsePort(value: String): Int? =
        when {
            !CharRules.isDigits(value) -> null
            CharRules.hasLeadingZero(value) -> null
            else -> value.toIntOrNull()?.takeIf { it in MIN_PORT..MAX_PORT }
        }

    private fun defaultPort(scheme: String): Int =
        when (scheme) {
            ValidatedServerAddress.SCHEME_HTTP -> HTTP_DEFAULT_PORT
            else -> HTTPS_DEFAULT_PORT
        }

    private fun normalizeBasePath(
        raw: String,
        errors: MutableSet<ServerAddressError>,
    ): String? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) {
            return DEFAULT_BASE_PATH
        }
        val normalized = normalizedBasePath(trimmed)
        if (normalized == null) {
            errors += ServerAddressError.BASE_PATH
        }
        return normalized
    }

    private fun normalizedBasePath(value: String): String? {
        val candidate = withLeadingSlash(value)
        if (CharRules.hasForbiddenPathChars(value)) {
            return null
        }
        return if (isValidPathShape(candidate)) candidate else null
    }

    private fun withLeadingSlash(value: String): String =
        if (value.startsWith(PATH_SEPARATOR_CHAR)) value else PATH_SEPARATOR_CHAR + value

    private fun isValidPathShape(value: String): Boolean =
        !value.contains(DOUBLE_SEPARATOR) && !hasTrailingSeparator(value)

    private fun hasTrailingSeparator(value: String): Boolean = value.length > 1 && value.endsWith(PATH_SEPARATOR_CHAR)

    private val SUPPORTED_SCHEMES =
        setOf(ValidatedServerAddress.SCHEME_HTTP, ValidatedServerAddress.SCHEME_HTTPS)
    private const val MIN_PORT = 1
    private const val MAX_PORT = 65_535
    private const val HTTP_DEFAULT_PORT = 80
    private const val HTTPS_DEFAULT_PORT = 443
    private const val DEFAULT_BASE_PATH = "/api"
    private const val DOUBLE_SEPARATOR = "//"
    private const val PATH_SEPARATOR_CHAR = '/'
}

internal object HostRules {
    fun normalizedHost(value: String): String? =
        when {
            CharRules.hasInvalidHostChars(value) -> null
            value.startsWith(IPV6_OPEN_BRACKET) || value.endsWith(IPV6_CLOSE_BRACKET) -> bracketedIpv6(value)
            value.contains(IPV6_SEPARATOR) -> bareIpv6(value)
            SCHEME_PREFIX_REGEX.containsMatchIn(value) -> null
            else -> plainHost(value)
        }

    private fun bracketedIpv6(value: String): String? {
        val bare = value.removePrefix(IPV6_OPEN_BRACKET).removeSuffix(IPV6_CLOSE_BRACKET)
        return if (Ipv6Rules.isIpv6(bare)) value else null
    }

    private fun bareIpv6(value: String): String? {
        if (Ipv6Rules.isIpv6(value)) {
            return IPV6_OPEN_BRACKET + value + IPV6_CLOSE_BRACKET
        }
        return null
    }

    private fun plainHost(value: String): String? {
        val lower = value.lowercase()
        return when {
            isIpv4(lower) -> lower
            IPV4_LIKE_REGEX.matches(lower) -> null
            isHostname(lower) -> lower
            else -> null
        }
    }

    private fun isIpv4(value: String): Boolean {
        val octets = value.split(IPV4_SEPARATOR)
        return octets.size == IPV4_OCTETS && octets.all { isOctet(it) }
    }

    private fun isOctet(value: String): Boolean = hasValidOctetLength(value) && isOctetDigits(value)

    private fun hasValidOctetLength(value: String): Boolean = value.length in OCTET_MIN_LENGTH..OCTET_MAX_LENGTH

    private fun isOctetDigits(value: String): Boolean =
        !CharRules.hasLeadingZero(value) && CharRules.isDigits(value) && value.toInt() <= MAX_IPV4_OCTET

    private fun isHostname(value: String): Boolean =
        value.length <= MAX_HOSTNAME_LENGTH &&
            value.split(HOSTNAME_SEPARATOR).all { isLabel(it) }

    private fun isLabel(label: String): Boolean =
        CharRules.hasValidLabelLength(label) &&
            !CharRules.hasEdgeHyphen(label) &&
            label.all { CharRules.isHostnameChar(it) }

    private val SCHEME_PREFIX_REGEX = Regex("^[a-z][a-z0-9+.-]*:")
    private val IPV4_LIKE_REGEX = Regex("^[0-9]+(\\.[0-9]+)+$")
    private const val IPV6_OPEN_BRACKET = "["
    private const val IPV6_CLOSE_BRACKET = "]"
    private const val IPV6_SEPARATOR = ":"
    private const val IPV4_SEPARATOR = "."
    private const val IPV4_OCTETS = 4
    private const val OCTET_MIN_LENGTH = 1
    private const val OCTET_MAX_LENGTH = 3
    private const val MAX_IPV4_OCTET = 255
    private const val HOSTNAME_SEPARATOR = "."
    private const val MAX_HOSTNAME_LENGTH = 253
}

internal object Ipv6Rules {
    fun isIpv6(value: String): Boolean =
        when {
            value.isEmpty() -> false
            value.split(IPV6_COMPRESSION).size > 2 -> false
            else -> validateGroups(value)
        }

    private fun validateGroups(value: String): Boolean {
        val halves = value.split(IPV6_COMPRESSION)
        return if (halves.size == COMPRESSED_HALVES) {
            isValidCompressedPair(halves[0], halves[1])
        } else {
            groupsOf(halves[0])?.size == GROUP_COUNT
        }
    }

    private fun isValidCompressedPair(
        left: String,
        right: String,
    ): Boolean =
        if (left.isEmpty() && right.isEmpty()) {
            true
        } else {
            compressedGroupCount(left, right) < GROUP_COUNT
        }

    private fun compressedGroupCount(
        left: String,
        right: String,
    ): Int {
        val leftGroups = groupsOf(left)
        val rightGroups = groupsOf(right)
        if (leftGroups == null || rightGroups == null) {
            return INVALID_GROUP_COUNT
        }
        return leftGroups.size + rightGroups.size
    }

    private fun groupsOf(segment: String): List<String>? =
        when {
            segment.isEmpty() -> emptyList()
            else ->
                segment
                    .split(IPV6_SEPARATOR)
                    .takeIf { groups -> groups.none { it.isEmpty() } && groups.all { isIpv6Group(it) } }
        }

    private fun isIpv6Group(group: String): Boolean =
        group.length in GROUP_MIN_LENGTH..GROUP_MAX_LENGTH && group.all { CharRules.isHexChar(it) }

    private const val IPV6_SEPARATOR = ":"
    private const val IPV6_COMPRESSION = "::"
    private const val GROUP_COUNT = 8
    private const val COMPRESSED_HALVES = 2
    private const val GROUP_MIN_LENGTH = 1
    private const val GROUP_MAX_LENGTH = 4
    private const val INVALID_GROUP_COUNT = 9
}

internal object CharRules {
    fun hasInvalidHostChars(value: String): Boolean =
        value.isEmpty() || value.any { it.isWhitespace() } || hasHostSeparators(value)

    private fun hasHostSeparators(value: String): Boolean =
        value.contains(SCHEME_SEPARATOR) || value.contains(PATH_SEPARATOR)

    fun hasForbiddenPathChars(value: String): Boolean =
        value.any { it.isWhitespace() || it == BACKSLASH_CHAR } ||
            value.contains(QUERY_SEPARATOR) ||
            value.contains(FRAGMENT_SEPARATOR)

    fun hasLeadingZero(value: String): Boolean = value.length > 1 && value.startsWith(ZERO)

    fun hasValidLabelLength(label: String): Boolean = label.length in LABEL_MIN_LENGTH..MAX_LABEL_LENGTH

    fun hasEdgeHyphen(label: String): Boolean = label.startsWith(HYPHEN) || label.endsWith(HYPHEN)

    fun isDigits(value: String): Boolean = value.all { it in '0'..'9' }

    fun isHexChar(char: Char): Boolean = char in '0'..'9' || char in 'a'..'f' || char in 'A'..'F'

    fun isHostnameChar(char: Char): Boolean = char in 'a'..'z' || char in 'A'..'Z' || isLabelSymbol(char)

    private fun isLabelSymbol(char: Char): Boolean = char in '0'..'9' || char == HYPHEN_CHAR

    private const val SCHEME_SEPARATOR = "://"
    private const val PATH_SEPARATOR = "/"
    private const val QUERY_SEPARATOR = "?"
    private const val FRAGMENT_SEPARATOR = "#"
    private const val BACKSLASH_CHAR = '\\'
    private const val ZERO = "0"
    private const val LABEL_MIN_LENGTH = 1
    private const val MAX_LABEL_LENGTH = 63
    private const val HYPHEN = "-"
    private const val HYPHEN_CHAR = '-'
}
