package com.smartnotebook.core.model.setup

public data class ServerAddressValidation(
    val address: ValidatedServerAddress?,
    val errors: Set<ServerAddressError>,
) {
    public val isValid: Boolean
        get() = address != null && errors.isEmpty()
}
