package com.smartnotebook.core.model

public sealed interface WireResult<out T> {
    public data class Success<T>(
        public val value: T,
    ) : WireResult<T>

    public data class Failure(
        public val error: WireDecodeError,
    ) : WireResult<Nothing>

    public val isSuccess: Boolean
        get() = this is Success

    public val isFailure: Boolean
        get() = this is Failure

    public fun getOrNull(): T? = (this as? Success)?.value

    public fun <R> map(transform: (T) -> R): WireResult<R> =
        when (this) {
            is Success -> Success(transform(value))
            is Failure -> this
        }

    public companion object {
        public fun <T> success(value: T): WireResult<T> = Success(value)

        public fun <T> failure(error: WireDecodeError): WireResult<T> = Failure(error)
    }
}

public sealed interface WireDecodeError {
    public val message: String

    public data class InvalidPayload(
        override val message: String,
    ) : WireDecodeError
}
