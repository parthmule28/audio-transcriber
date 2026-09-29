# Task 8 — Transcription Pipeline Report

## Outcome

Implemented the transcription pipeline with bounded parallel chunk processing, ordered transcript assembly, partial reports, explicit retry of failed spans, 429-only retries, cancellation, and temporary-file cleanup.

The pipeline never opens its own network connection: transcription and best-effort close calls go only through the injected client. Unexpected per-chunk exceptions are converted to a generic `TranscriberError` so details such as private paths, audio, transcripts, or credentials are not placed in a report or callback.

## Files changed

- `src/audio_transcriber/pipeline.py` — pipeline, callbacks, outcomes, and reports.
- `src/audio_transcriber/constants.py` — added `SILENCE_NOISE_DB = -35.0` and `SILENCE_MIN_DURATION = 0.4`, which the Task 8 brief references but the existing constants module did not define.
- `tests/test_pipeline.py` — deterministic tests using fake media operations, fake clients/workspaces, and injected sleep; chunk planning and thread scheduling remain real.
- `tests/test_constants.py` — pins the two silence-detection settings used by the pipeline.

## Behavior implemented

- Runs media probing, quiet-point detection, and fixed chunk planning in sequence; propagates `NoAudioStreamError`.
- Extracts chunks lazily in workers, schedules at most `MAX_CONCURRENT_REQUESTS` (3), and stops scheduling after cancellation.
- Assembles transcript text in ascending chunk index regardless of completion order.
- Reports cost and usage seconds only when the report is complete and every chunk includes the respective usage value.
- Retries only `RateLimitError`, up to `MAX_RATE_LIMIT_RETRIES`, honors a supplied `Retry-After`, otherwise uses bounded exponential delays, and does not retry timeout or provider errors.
- Preserves completed results on cancellation, closes the injected client best-effort, removes per-chunk WAVs, and always cleans the workspace.
- `retry_failed()` resubmits only indices in the previous report’s failures, merges outcomes, and emits a `UserWarning` before resubmitting to note possible additional charges.

## TDD and verification

Tests were written before implementation and the initial red check failed during collection as expected:

```text
$ source .venv/bin/activate && python -m pytest tests/test_pipeline.py -v
ERROR collecting tests/test_pipeline.py
ModuleNotFoundError: No module named 'audio_transcriber.pipeline'
```

The referenced silence constants were absent from the prior module. The focused test failed before they were added:

```text
$ source .venv/bin/activate && python -m pytest tests/test_constants.py::test_pipeline_silence_detection_settings_are_pinned -v
FAILED — AttributeError: module 'audio_transcriber.constants' has no attribute 'SILENCE_NOISE_DB'
```

Additional red checks exposed stale failures surviving a successful retry, client-close exceptions escaping during cancellation, unexpected chunk errors aborting the entire run, and a failed new run retaining prior retry state. Each was fixed and covered by a regression test.

Final targeted pipeline run:

```text
$ source .venv/bin/activate && python -m pytest tests/test_pipeline.py -q
....................                                                     [100%]
20 passed in 0.09s
```

Final full suite:

```text
$ source .venv/bin/activate && python -m pytest tests/ -q
........................................................................ [ 59%]
..................................................                       [100%]
122 passed in 0.61s
```

Additional checks:

```text
$ source .venv/bin/activate && python -m compileall -q src/audio_transcriber tests
Exit code: 0; no output

$ git diff --check
Exit code: 0; no output
```

The system `python` shim has no mise version configured. Activating the repository’s `.venv` before running the commands above selects the project interpreter and pytest.

## Commit

- `902959b41c48cd888c307637d175ec98a6a90aa7` — `feat: orchestrate parallel chunk transcription with retry and cancellation`

This report is versioned separately from the implementation commit.

## Self-review and concerns

- Confirmed the worker window is bounded to three; result assembly is index-ordered; timeout, 502, and 503 failures are not retried; retries replace the prior failure entry; and workspace cleanup runs on success, cancellation, and preparation failure.
- Silence detection settings had to be added because Task 8 explicitly consumes them but Tasks 1–4 had not defined them. The values match the existing audio test settings (`-35.0 dB`, `0.4 s`).
- The retry-charge notice is a standard Python `UserWarning`, not a GUI callback. A UI that must guarantee a visible confirmation should present it before calling `retry_failed()`.
- Cancellation closes the injected `OpenRouterClient` best-effort. Since that client is not reopenable through the existing interface, retrying failures from a cancelled run with the same closed client may yield another partial report; callers needing that flow will need a fresh client/pipeline lifecycle.

## Task 8 review-fix report

### Findings fixed

1. Cancellation now adds `CancelledError` failures for spans in the current attempt that have neither a result nor another recorded failure. This includes spans never scheduled after cancellation, making them visible to `retry_failed()` while retaining successful in-flight results.
2. `cancel()` now only signals the cancellation event. It does not close the injected client; its lifecycle remains caller-owned, so `retry_failed()` can resubmit spans using the same `OpenRouterClient`.
3. Retry reports derive `cancelled` only from the retry attempt's event. A successful retry clears the previous cancellation state and publishes through `on_finished`; a retry that is newly cancelled publishes through `on_cancelled`.

### Regression tests and TDD evidence

The focused red run reproduced the review findings:

```text
$ source .venv/bin/activate && python -m pytest tests/test_pipeline.py -k "cancelled_run_marks or cancelled_spans_retry or successful_retry_clears or cancel_during_backoff" -v
FAILED test_cancelled_run_marks_unstarted_spans_as_failed — expected unstarted index 4 in failures, got none
FAILED test_cancelled_spans_retry_with_the_same_open_client — retry emitted no charge warning because it had no failed spans
FAILED test_successful_retry_clears_cancelled_state_and_publishes_finished — retry emitted no charge warning because it had no failed spans
FAILED test_cancel_during_backoff_stops_before_another_request — expected close_calls == 0, got 1
4 failed, 18 deselected in 0.16s
```

Focused pipeline tests after the fixes:

```text
$ source .venv/bin/activate && python -m pytest tests/test_pipeline.py -q
......................                                                   [100%]
22 passed in 0.14s
```

Full suite after the fixes:

```text
$ source .venv/bin/activate && python -m pytest tests/ -q
........................................................................ [ 58%]
....................................................                     [100%]
124 passed in 0.66s
```

Additional checks:

```text
$ source .venv/bin/activate && python -m compileall -q src/audio_transcriber tests
Exit code: 0; no output

$ git diff --check
Exit code: 0; no output
```

### Fix commit

- `990ab8d1c7db1d9c06e26fed1b0ce88a74bcf53e` — `fix: preserve cancelled chunks for retry with reusable client`

### Updated concerns

- The prior concern that cancellation leaves the same client permanently closed is resolved: the pipeline no longer closes the injected client. In-flight HTTP requests are therefore allowed to finish instead of being forcibly closed; already-sent requests may still complete or be billed, consistent with best-effort cancellation.
- The retry-charge notice remains a Python `UserWarning`, not a GUI callback. A UI that requires visible confirmation should present it before calling `retry_failed()`.
