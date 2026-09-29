class TranscriberError(Exception):
    user_message = "The transcription could not be completed."
    retryable = False


class CredentialStoreUnavailable(TranscriberError):
    user_message = "Secure credential storage is unavailable. The application cannot proceed safely."


class FfmpegMissingError(TranscriberError):
    user_message = "FFmpeg or FFprobe was not found next to the application or on PATH."


class AudioPreparationError(TranscriberError):
    user_message = "The audio could not be prepared for transcription."


class NoAudioStreamError(AudioPreparationError):
    user_message = "The selected file does not contain an audio track."


class ModelDiscoveryError(TranscriberError):
    user_message = "The available transcription models could not be fetched."


class NoApprovedModelAvailable(ModelDiscoveryError):
    user_message = "Neither approved transcription model is available for this key."


class ApiError(TranscriberError):
    user_message = "The transcription provider returned an error."

    def __init__(self, message: str = "", *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(ApiError):
    user_message = "The API key is invalid. Check the key and try again."


class InsufficientCreditsError(ApiError):
    user_message = "The account or API key has insufficient credits."


class ForbiddenError(ApiError):
    user_message = "The request is blocked by API key or account restrictions."


class InvalidRequestError(ApiError):
    user_message = "The audio or transcription request is not supported."


class RateLimitError(ApiError):
    user_message = "The provider is rate limiting requests. Please try again shortly."
    retryable = True

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message, status_code=status_code)
        self.retry_after = retry_after


class RequestTimeoutError(ApiError):
    user_message = "The request timed out. It may already have been processed or billed."


class ProviderError(ApiError):
    user_message = "The upstream provider failed. The request may already have been billed."


class CancelledError(TranscriberError):
    user_message = "The transcription was cancelled."


EXPORTED_ERRORS = (
    "TranscriberError",
    "CredentialStoreUnavailable",
    "FfmpegMissingError",
    "AudioPreparationError",
    "NoAudioStreamError",
    "ModelDiscoveryError",
    "NoApprovedModelAvailable",
    "ApiError",
    "AuthenticationError",
    "InsufficientCreditsError",
    "ForbiddenError",
    "InvalidRequestError",
    "RateLimitError",
    "RequestTimeoutError",
    "ProviderError",
    "CancelledError",
)

__all__ = (*EXPORTED_ERRORS, "EXPORTED_ERRORS")
