from audio_transcriber import errors


def test_every_error_has_a_readable_message():
    for name in errors.EXPORTED_ERRORS:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.TranscriberError)
        assert cls("boom").user_message.strip()
        assert "boom" not in cls("secret-value").user_message


def test_ambiguous_failures_are_flagged_not_retryable():
    assert errors.RequestTimeoutError("t").retryable is False
    assert errors.ProviderError("p").retryable is False
    assert errors.RateLimitError("r").retryable is True


def test_api_errors_carry_status_and_rate_limit_retry_after():
    assert errors.ApiError("x", status_code=400).status_code == 400
    assert errors.RateLimitError("x", status_code=429, retry_after=1.5).retry_after == 1.5
