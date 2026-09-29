from audio_transcriber import constants


def test_chunk_constants_are_pinned():
    assert constants.TARGET_CHUNK_SECONDS == 30
    assert constants.OVERLAP_SECONDS == 1
    assert constants.MAX_CONCURRENT_REQUESTS == 3


def test_only_approved_whisper_models_are_allowed():
    assert constants.ALLOWED_MODELS == (
        "openai/whisper-large-v3-turbo",
        "openai/whisper-large-v3",
    )
    assert constants.DEFAULT_MODEL == "openai/whisper-large-v3-turbo"
    assert "openai/whisper-1" not in constants.ALLOWED_MODELS
    assert "openai/text-embedding-3-large" not in constants.ALLOWED_MODELS


def test_zdr_warning_matches_spec_verbatim():
    assert constants.ZDR_WARNING == (
        "ZDR must be enforced on this API key/account. "
        "The application cannot verify or enforce this for transcription."
    )


def test_transport_audio_and_retry_constants_are_pinned():
    assert constants.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"
    assert constants.CANONICAL_SAMPLE_RATE == 16000
    assert constants.CANONICAL_CHANNELS == 1
    assert constants.CANONICAL_FORMAT == "wav"
    assert constants.MAX_RATE_LIMIT_RETRIES == 3
    assert constants.RETRY_BASE_DELAY_SECONDS == 2.0
    assert isinstance(constants.LANGUAGES, tuple)
    assert constants.LANGUAGES


def test_boundary_dedup_constants_are_pinned():
    assert constants.MIN_BOUNDARY_DEDUP_TOKENS == 3
    assert constants.MAX_BOUNDARY_DEDUP_TOKENS == 20
