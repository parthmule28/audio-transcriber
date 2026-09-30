# Final Fix Report — Windows Audio Transcriber

## Outcome

- Addressed final-review Important findings 1–8 and both feasible Minor findings (version drift and cancellation progress). Chunk spans now preserve continuous audio coverage; language choices send ISO-639-1 codes; model discovery is asynchronous; saved keys can be replaced/forgotten; startup cleanup is ownership-aware; and FFmpeg work is bounded and cancellable.
- Final review caught and fixed an additional Windows safety defect: CPython's Windows `os.kill(pid, 0)` implementation uses `TerminateProcess`. Workspace cleanup now uses `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` and `GetExitCodeProcess` on Windows, preserving inaccessible/unknown processes without signaling them.
- The approved unpinned BtbN FFmpeg `latest` URL remains unchanged. Packaging fails closed until exact corresponding FFmpeg source, matching metadata, maintainer verification, and a substantive written offer are supplied. No redistribution-compliance claim is made.

## Verification

| Command | Result |
| --- | --- |
| `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_main_window.py tests/test_pipeline.py tests/test_workdir.py -q` | **62 passed** |
| `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/test_build_release.py tests/test_release_workflow.py tests/test_license_material.py -q` | **28 passed** |
| `QT_QPA_PLATFORM=offscreen .venv/bin/pytest -q` | **197 passed, 1 skipped**; the skip is the opt-in sample test without `AUDIO_TRANSCRIBER_SAMPLE` |
| `AUDIO_TRANSCRIBER_SAMPLE='/home/parth/Desktop/Code/scripts/audio-script/Voice 260810_110617.m4a' PYTHONPATH=src QT_QPA_PLATFORM=offscreen ./.venv/bin/python -m pytest tests/test_end_to_end.py -v` | **1 passed**; real local-media processing with mocked API transport and network guard |
| `git diff --check` | Passed |

The cancellation-progress regression first failed with progress `1` rather than `2`, then passed in the focused UI/pipeline run. The Windows process-state regression first demonstrated that the old path called `os.kill`; both new workspace tests pass with a mocked Win32 query API. The first opt-in end-to-end run exposed a test wrapper that did not accept the new cancellation parameters; the wrapper now forwards `cancel_event` and `timeout`, and the rerun passed.

## Release blockers and unverified items

- `packaging/ffmpeg-source-compliance/` contains only its README; the exact source archive, `SOURCE-METADATA.txt`, and `SOURCE-OFFER.md` are absent. The source-material collector test verifies fail-closed behavior. Do not create/publish a release until maintainers establish source correspondence and required notices for the exact fetched binary.
- PyInstaller is unavailable in the local `.venv`, and verification ran on Linux. The real Windows dependency-license inventory and Windows release build were not run; package/license tests use a fake packaging environment. This remains unverified independently of the explicit FFmpeg source blocker.
- The earlier Task 10 note about the internal selected-file test state was judged artificial by final review and remains deferred; no behavior change was made for that note.
