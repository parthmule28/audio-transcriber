# Task 12 Implementation Report — Windows Onedir Packaging

## Outcome

Implemented the PyInstaller onedir spec, FFmpeg/FFprobe fetcher, and release ZIP builder. The ZIP root is `AudioTranscriber/`, with the app executable, bundled tools, PyInstaller runtime files, and `LICENSES/` assets in their onedir locations. Media and secret-like paths are filtered while the archive is written.

## Files changed

- `packaging/AudioTranscriber.spec` — creates an `Analysis`/`EXE`/`COLLECT` onedir build; disables the console; sets `contents_directory="."` to keep support files beside the executable; includes FFmpeg/FFprobe and `LICENSES` only when present; excludes unused Qt and test modules; explicitly includes the dynamically imported self-test.
- `packaging/fetch_ffmpeg.py` — downloads the BtbN latest Windows GPL archive only when either binary is missing, extracts only the expected `bin/ffmpeg.exe` and `bin/ffprobe.exe`, stages outputs before replacement, and reports errors with the source URL.
- `packaging/build_release.py` — runs PyInstaller with an argv list in isolated temporary directories, creates `AudioTranscriber-v<version>-win-x64.zip`, and excludes audio extensions, `.env` paths, and any path component containing `key`.
- `tests/test_build_release.py` — fake PyInstaller runner tests archive naming/layout, exclusions, optional spec assets, FFmpeg fetching, and behavior when PyInstaller is absent.
- `tests/test_selftest.py` — adds coverage that the existing self-test log is written when windowed execution has no usable stdout.
- `.superpowers/sdd/2026-09-29-windows-audio-transcriber/task-12-report.md` — this implementation and verification report; committed separately from the implementation.

## Commits

- `21d554bb206ea1a1558ae3ddefa7842ac561ae2e` — `build: package onedir Windows app with bundled FFmpeg`

## Verification

### Targeted packaging tests

Command:

```text
uvx --from pytest pytest tests/test_build_release.py -v
```

Output:

```text
collected 8 items
tests/test_build_release.py::test_zip_contains_expected_layout_and_name PASSED
tests/test_build_release.py::test_zip_root_folder_is_named_for_the_app PASSED
tests/test_build_release.py::test_zip_excludes_media_environment_and_key_files PASSED
tests/test_build_release.py::test_spec_is_parseable_onedir_and_includes_only_existing_optional_assets PASSED
tests/test_build_release.py::test_fetch_returns_existing_binaries_without_downloading PASSED
tests/test_build_release.py::test_fetch_downloads_only_the_two_expected_binaries PASSED
tests/test_build_release.py::test_fetch_wraps_download_errors_with_the_source_url PASSED
tests/test_build_release.py::test_default_build_runner_uses_argv_and_reports_missing_pyinstaller PASSED
============================== 8 passed in 0.04s ===============================
```

### Full available test suite

The base environment lacked pytest and the application runtime dependencies. The full suite was run in an ephemeral `uv` environment with the declared runtime/test dependencies; it did not modify project dependency files.

Command:

```text
PYTHONPATH=src QT_QPA_PLATFORM=offscreen uv run --no-project --with pytest --with pytest-qt --with pyside6 --with httpx --with keyring -- python -m pytest -q
```

Output:

```text
........................................................................ [ 43%]
........................................................................ [ 87%]
....................                                                     [100%]
164 passed in 1.18s
```

### Additional checks

```text
python -c "import ast,pathlib; ast.parse(pathlib.Path('packaging/AudioTranscriber.spec').read_text()); print('spec parses')"
spec parses
```

```text
python -m py_compile packaging/fetch_ffmpeg.py packaging/build_release.py tests/test_build_release.py tests/test_selftest.py
```

The compile command exited 0 with no output. `git diff --cached --check` also exited 0 with no output before the implementation commit.

### TDD/red-phase evidence and environment notes

- Initial exact brief command, `python -m pytest tests/test_build_release.py -v`, could not start because the active Python reported `No module named pytest` (exit 1). `uvx` was used for the targeted tests instead.
- Before implementation, `uvx --from pytest pytest tests/test_build_release.py -v` failed collection with the expected `ModuleNotFoundError: No module named 'build_release'` (exit 2).
- While reviewing PyInstaller 6's onedir behavior, the spec test was extended to require `contents_directory="."`. The new assertion first failed with `KeyError: 'contents_directory'`, then passed after the spec fix (one test passed).
- A preliminary stdout-unavailable self-test assertion expected the overall self-test to pass, but the minimal environment lacked PySide6, so `qt-initialised` correctly failed. The test was narrowed to verify the required log contents independently of optional runtime availability; it passes in the full dependency-enabled suite.

## Self-review findings and concerns

- PyInstaller 6 defaults supporting files into `_internal`; the explicit `contents_directory="."` preserves the expected flat onedir layout and lets the existing binary resolver find FFmpeg/FFprobe beside `AudioTranscriber.exe`.
- The spec's existence checks and the builder's deferred PyInstaller subprocess keep imports and fake-runner tests safe when Windows binaries or PyInstaller are absent on Linux. The default runner reports a clear `RuntimeError` for a missing/failed PyInstaller invocation.
- No actual Windows executable build or live FFmpeg download was performed in this Linux environment. Packaging behavior was verified with a fake runner and mocked archive download; a Windows release build remains necessary for release validation.
- The upstream `latest` archive is not checksum-pinned in v1, as required; the limitation is documented in `fetch_ffmpeg.py`.
- The requested broad `*key*` path exclusion can also filter legitimate asset names that contain `key`; it is implemented literally to avoid archiving key-like paths.
- The pre-existing untracked `src/audio_transcriber.egg-info/` was left untouched. Git also emitted its automatic committer identity warning for the implementation commit; no global identity settings were changed.
