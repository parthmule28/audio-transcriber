import base64
import json

import httpx
import pytest

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
from audio_transcriber.openrouter_client import OpenRouterClient, TranscriptionResponse, Usage


def _client(handler) -> OpenRouterClient:
    return OpenRouterClient("sk-or-v1-test", transport=httpx.MockTransport(handler))


def test_discovery_returns_allowlisted_models_in_allowlist_order():
    def handler(request):
        assert request.url.path == "/api/v1/models/user"
        assert request.url.params["output_modalities"] == "transcription"
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test"
        return httpx.Response(200, json={"data": [
            {"id": "openai/whisper-large-v3"},
            {"id": "openai/whisper-1"},
            {"id": "openai/whisper-large-v3-turbo"},
            {"id": "openai/whisper-large-v3"},
        ]})

    with _client(handler) as client:
        assert client.list_available_models() == [
            "openai/whisper-large-v3-turbo", "openai/whisper-large-v3",
        ]


def test_discovery_does_not_fall_back_to_unapproved_models():
    with _client(lambda request: httpx.Response(200, json={"data": [
        {"id": "openai/whisper-1"},
    ]})) as client:
        assert client.list_available_models() == []


def test_discovery_unmapped_error_is_model_discovery_error():
    with _client(lambda request: httpx.Response(418, text="secret transcript")) as client:
        with pytest.raises(ModelDiscoveryError) as raised:
            client.list_available_models()
    assert "secret transcript" not in str(raised.value)


@pytest.mark.parametrize(("status", "error_type"), [
    (400, InvalidRequestError),
    (401, AuthenticationError),
    (402, InsufficientCreditsError),
    (403, ForbiddenError),
    (408, RequestTimeoutError),
    (429, RateLimitError),
    (502, ProviderError),
    (503, ProviderError),
])
@pytest.mark.parametrize("endpoint", ["discovery", "transcribe"])
def test_http_errors_are_mapped_without_exposing_sensitive_content(tmp_path, status, error_type, endpoint):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"private audio")

    def handler(request):
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test"
        return httpx.Response(status, json={"error": {"message": "sk-or-v1-test private transcript"}})

    with _client(handler) as client, pytest.raises(error_type) as raised:
        if endpoint == "discovery":
            client.list_available_models()
        else:
            client.transcribe(audio, "openai/whisper-large-v3-turbo")
    assert raised.value.status_code == status
    assert "sk-or-v1-test" not in raised.value.user_message
    assert "private transcript" not in str(raised.value)


@pytest.mark.parametrize(("header", "expected"), [
    ("30", 30.0),
    (None, None),
    ("not-a-number", None),
])
def test_rate_limit_retry_after_is_numeric_or_none(header, expected):
    headers = {"Retry-After": header} if header is not None else {}
    with _client(lambda request: httpx.Response(429, headers=headers, text="not json")) as client:
        with pytest.raises(RateLimitError) as raised:
            client.list_available_models()
    assert raised.value.retry_after == expected


def test_unmapped_transcription_error_is_api_error(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"private audio")
    with _client(lambda request: httpx.Response(418, text="private transcript")) as client:
        with pytest.raises(ApiError) as raised:
            client.transcribe(audio, "openai/whisper-large-v3")
    assert type(raised.value) is ApiError
    assert "private transcript" not in str(raised.value)


def test_transcribe_sends_only_json_base64_audio_without_provider(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF\x00private audio")

    def handler(request):
        assert request.url.path == "/api/v1/audio/transcriptions"
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test"
        assert request.headers["Content-Type"] == "application/json"
        sent_body = json.loads(request.content)
        assert sent_body == {
            "model": "openai/whisper-large-v3-turbo",
            "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode("ascii"), "format": "wav"},
            "temperature": 0,
        }
        assert "provider" not in sent_body
        assert "language" not in sent_body
        return httpx.Response(200, json={"text": "Hello"})

    with _client(handler) as client:
        assert client.transcribe(audio, "openai/whisper-large-v3-turbo") == TranscriptionResponse(
            "Hello", None, None,
        )


def test_transcribe_includes_language_and_parses_independent_usage_fields(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")

    def handler(request):
        sent_body = json.loads(request.content)
        assert sent_body["language"] == "en"
        assert "provider" not in sent_body
        return httpx.Response(200, headers={"X-Generation-Id": "gen-123"}, json={
            "text": "Hello", "usage": {
                "seconds": "1.5", "total_tokens": "12", "input_tokens": 7,
                "output_tokens": "5",
            },
        })

    with _client(handler) as client:
        result = client.transcribe(audio, "openai/whisper-large-v3", language="en")
    assert result == TranscriptionResponse("Hello", Usage(1.5, 12, 7, 5, None), "gen-123")


def test_transcribe_malformed_usage_fields_do_not_replace_other_fields(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")
    with _client(lambda request: httpx.Response(200, json={
        "text": "Hello", "usage": {"seconds": "bad", "total_tokens": 8, "cost": "0.25"},
    })) as client:
        assert client.transcribe(audio, "openai/whisper-large-v3") == TranscriptionResponse(
            "Hello", Usage(None, 8, None, None, 0.25), None,
        )


@pytest.mark.parametrize("model", ["openai/whisper-1", "openai/gpt-4o-transcribe"])
def test_transcribe_rejects_unapproved_models_without_sending_request(tmp_path, model):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")

    def handler(request):
        pytest.fail("unapproved model was sent")

    with _client(handler) as client:
        with pytest.raises(InvalidRequestError):
            client.transcribe(audio, model)


def test_transcribe_wraps_httpx_timeout_without_sensitive_message(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF")

    def handler(request):
        raise httpx.ReadTimeout("sk-or-v1-test private transcript")

    with _client(handler) as client:
        with pytest.raises(RequestTimeoutError) as raised:
            client.transcribe(audio, "openai/whisper-large-v3")
    assert "sk-or-v1-test" not in str(raised.value)
    assert "private transcript" not in str(raised.value)


def test_discovery_malformed_success_response_is_model_discovery_error():
    with _client(lambda request: httpx.Response(200, text="not json")) as client:
        with pytest.raises(ModelDiscoveryError):
            client.list_available_models()
