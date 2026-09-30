# Task 14 Implementation Report — Opt-In Real-Media End-to-End Test

## Outcome

Added an opt-in test that uses `AUDIO_TRANSCRIBER_SAMPLE` as a local path, exercises real FFprobe/FFmpeg inspection and chunk extraction, and sends only the first three real planned chunks through `TranscriptionPipeline` and `OpenRouterClient` backed by `httpx.MockTransport`. The mock returns a canned transcript and per-chunk costs; a socket guard fails any non-mocked network connection. No production code changed and no real API request or billed call was made.

## Files changed

- `tests/test_end_to_end.py` — opt-in real-media pipeline test; confirms extracted chunks are 16 kHz mono `pcm_s16le`, and asserts the assembled mock transcript and summed mock cost.
- `.superpowers/sdd/2026-09-29-windows-audio-transcriber/task-14-report.md` — this report.

The sample media stayed outside the repository and no transcript was written. The pre-existing untracked `src/audio_transcriber.egg-info/` was left untouched.

## Commits

- `053e697` — `test: add opt-in end-to-end check against local media`
- This report is committed separately as `docs: record Task 14 implementation report`.

## Verification

### Opt-in test against the second supplied sample

Sample: `/home/parth/Desktop/Code/scripts/audio-script/Voice 260810_110617.m4a`.

Command:

```text
AUDIO_TRANSCRIBER_SAMPLE='/home/parth/Desktop/Code/scripts/audio-script/Voice 260810_110617.m4a' PYTHONPATH=src QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest tests/test_end_to_end.py -v
```

Output:

```text
tests/test_end_to_end.py::test_real_sample_runs_first_three_chunks_through_mocked_pipeline PASSED [100%]
============================== 1 passed in 10.43s ==============================
```

### Full suite

Command:

```text
PYTHONPATH=src QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest -q
```

Output:

```text
178 passed, 1 skipped in 1.89s
```

The skipped test is the new end-to-end test when the sample-path environment variable is not set.

### Real sample chunk and overlap counts

Real probe duration: `6247.155729s` (about 104 minutes); quiet detection found 809 midpoints. Planning against those points produced **216 chunks**, with `6462.155729s` total planned audio and **215.000000s (3m 35s) of overlap audio**.

### Repository scope

- The implementation commit contains only `tests/test_end_to_end.py`.
- `git diff --cached --check` passed before the test commit.
- No media or transcript was added to Git. The sample path is outside the repository.

## Remaining concern

Verification ran on Linux with the supplied real media and local FFmpeg tools; a Windows run was not available. The pipeline smoke test intentionally transcribes only the first three chunks to keep the real-media check bounded; it computes the full quiet-point chunk plan and records the complete count above.

The default system Python did not have pytest or the source package on its import path, so verification used the repository `.venv` and `PYTHONPATH=src`.
