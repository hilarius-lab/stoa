package com.smartnotebook.core.model.setup

public data class ValidatedServerAddress(
    val scheme: String,
    val host: String,
    val port: Int,
    val basePath: String,
) {
    public val isCleartext: Boolean
        get() = scheme == SCHEME_HTTP

    public companion object {
        public const val SCHEME_HTTP: String = "http"

        public const val SCHEME_HTTPS: String = "https"
    }
}
