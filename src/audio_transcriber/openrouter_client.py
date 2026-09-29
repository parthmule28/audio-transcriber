"""OpenRouter transcription and approved-model discovery over HTTP."""

import base64
import math
from pathlib import Path
from typing import NamedTuple

import httpx

from audio_transcriber import constants
from audio_transcriber.errors import (
    ApiError,
    AuthenticationError,
    ForbiddenError,
    InsufficientCreditsError,
    InvalidRequestError,
    ModelDiscoveryError,
    ProviderError,
    RateLimitError,
    RequestTimeoutError,
)


class Usage(NamedTuple):
    seconds: float | None
    total_tokens: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost: float | None


class TranscriptionResponse(NamedTuple):
    text: str
    usage: Usage | None
    generation_id: str | None


_STATUS_ERRORS = {
    400: (InvalidRequestError, "Invalid transcription request."),
    401: (AuthenticationError, "Invalid API credentials."),
    402: (InsufficientCreditsError, "Insufficient credits."),
    403: (ForbiddenError, "Request forbidden."),
    408: (RequestTimeoutError, "Request timed out."),
    429: (RateLimitError, "Rate limited."),
    502: (ProviderError, "Upstream provider failed."),
    503: (ProviderError, "Upstream provider unavailable."),
}


def _coerce(value: object, converter):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = converter(value)
        if isinstance(result, float) and not math.isfinite(result):
            return None
        return result
    except (TypeError, ValueError, OverflowError):
        return None


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 200:
        return
    try:
        body = response.json()
        error = body.get("error", {}) if isinstance(body, dict) else {}
        if not isinstance(error, dict):
            error = {}
    except (ValueError, TypeError):
        error = {}
    # Upstream error text is untrusted; never put it in an exception or log.
    del error
    error_type, message = _STATUS_ERRORS.get(
        response.status_code, (ApiError, "The transcription provider returned an error."),
    )
    if error_type is RateLimitError:
        retry_after = _coerce(response.headers.get("Retry-After"), float)
        raise RateLimitError(message, status_code=response.status_code, retry_after=retry_after)
    raise error_type(message, status_code=response.status_code)


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
    ):
        self._client = httpx.Client(
            base_url=constants.OPENROUTER_BASE_URL,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def list_available_models(self) -> list[str]:
        try:
            response = self._client.get("/models/user", params={"output_modalities": "transcription"})
        except httpx.TimeoutException:
            raise RequestTimeoutError("Request timed out.") from None
        if response.status_code != 200 and response.status_code not in _STATUS_ERRORS:
            raise ModelDiscoveryError("The available transcription models could not be fetched.")
        _raise_for_status(response)
        try:
            available = {entry["id"] for entry in response.json()["data"]}
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ModelDiscoveryError("The model list could not be read.") from None
        return [model for model in constants.ALLOWED_MODELS if model in available]

    def transcribe(
        self, wav_path: Path, model: str, language: str | None = None,
    ) -> TranscriptionResponse:
        if model not in constants.ALLOWED_MODELS:
            raise InvalidRequestError("The selected transcription model is not approved.")
        audio_data = base64.b64encode(wav_path.read_bytes()).decode("ascii")
        body = {
            "model": model,
            "input_audio": {"data": audio_data, "format": "wav"},
            "temperature": 0,
        }
        if language is not None:
            body["language"] = language
        try:
            response = self._client.post("/audio/transcriptions", json=body)
        except httpx.TimeoutException:
            raise RequestTimeoutError("Request timed out.") from None
        _raise_for_status(response)
        try:
            result = response.json()
            text = result["text"]
            if not isinstance(text, str):
                raise TypeError("invalid text")
            raw_usage = result.get("usage")
            usage = None
            if isinstance(raw_usage, dict):
                usage = Usage(
                    seconds=_coerce(raw_usage.get("seconds"), float),
                    total_tokens=_coerce(raw_usage.get("total_tokens"), int),
                    input_tokens=_coerce(raw_usage.get("input_tokens"), int),
                    output_tokens=_coerce(raw_usage.get("output_tokens"), int),
                    cost=_coerce(raw_usage.get("cost"), float),
                )
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ApiError("The transcription response could not be read.") from None
        return TranscriptionResponse(text, usage, response.headers.get("X-Generation-Id"))

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenRouterClient":
        self._client.__enter__()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._client.__exit__(exc_type, exc_value, traceback)
