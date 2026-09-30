# Task 11 implementation report

## Files changed
- `src/audio_transcriber/selftest.py`: ordered Python/Qt/FFmpeg/FFprobe diagnostics, structured results, stdout and adjacent `self-test.log` reporting. Probe and binary resolver injection keep tests deterministic.
- `src/audio_transcriber/__main__.py`: retained Task 10 dispatch; adapts structured self-test results to conventional process exit status while preserving direct integer probe implementations.
- `tests/test_selftest.py`: success/failure, ordered checks, log parity, and forbidden network/credential access coverage.

## Tests and commands
- `.venv/bin/python -m pytest tests/test_selftest.py -v` — initially failed at collection as expected (`ModuleNotFoundError: audio_transcriber.selftest`); after implementation: **4 passed**.
- `.venv/bin/python -m pytest tests/test_selftest.py tests/test_main_window.py -q` — **24 passed**.
- `.venv/bin/python -m pytest -q` — **155 passed**.
- `.venv/bin/python -m audio_transcriber --self-test; echo "exit=$?"` — four PASS lines (`python-version`, `qt-initialised`, `ffmpeg`, `ffprobe`), `exit=0`.
- Plain `python -m pytest tests/test_selftest.py -v` was also attempted, but the system Python does not have pytest installed; used the repository `.venv` thereafter.

## Self-review
- No MainWindow, credential store, sockets, or network APIs are used in the diagnostics.
- Qt initialization is offscreen, and an app instance created by this check is explicitly destroyed; if an application already exists (e.g. pytest-qt), it is correctly recognized as initialized.
- FFmpeg probes use `-version`, a 20-second timeout, and return-code validation; probe exceptions become failed check records.
- The documented brief is internally inconsistent: prose describes `run_self_test() -> int`, while its named result interface and test examples require `.checks`/`.ok`. Implemented the result object interface and translated `.ok` to an exit code at the CLI boundary. This permits detailed checks and correct process status.

## Concerns
- No outstanding functional concerns. Unrelated pre-existing untracked `src/audio_transcriber.egg-info/` was left untouched.

## Commit
- `e1fa8aff093c159456badd537a27a97d5e8839aa` — `feat: add headless self-test for Qt and bundled FFmpeg`
