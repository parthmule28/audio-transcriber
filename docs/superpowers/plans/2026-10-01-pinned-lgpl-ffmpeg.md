# Pinned LGPL FFmpeg and Windows CI Artifact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unpinned prebuilt GPL FFmpeg bundle with a pinned, source-built LGPL FFmpeg toolchain, then produce and upload a Windows test ZIP from CI without publishing a Release.

**Architecture:** Windows CI uses MSYS2 UCRT64 to build FFmpeg 9.0.2 from the official signed source archive, pinned by SHA-256 and verified against the FFmpeg release-signing key fingerprint. A checked-in build script enables only the app's local audio probe/decode, silence-detection, and canonical WAV-conversion features; shared FFmpeg libraries and the exact source, signature, license, build recipe, and generated provenance are included in the ZIP. The manual workflow run uploads an Actions artifact; tag-based GitHub Release behavior remains unchanged but will not be triggered for this task.

**Tech Stack:** Python 3.12, Bash/MSYS2 UCRT64, MinGW-w64 GCC, FFmpeg 9.0.2, PyInstaller, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-29-windows-audio-transcriber-design.md`; approved FFmpeg sourcing decision in the conversation on 2026-10-01.

## Global Constraints

- Keep the app's audio output at 16 kHz, mono, signed 16-bit PCM WAV.
- Keep the original recording unchanged; no source audio or API key may enter GitHub Actions.
- Build from FFmpeg 9.0.2's official source archive with the pinned SHA-256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` and verify its detached signature using the pinned FFmpeg release-key fingerprint `FCF986EA15E6E293A5644F10B4322F04D67658D8`.
- Configure FFmpeg with GPL, version-3-only, nonfree, autodetection, and network support disabled; enable only reviewed components needed by the app's advertised WAV, MP3, M4A, MP4, MOV, FLAC, and OGG inputs and build shared FFmpeg libraries.
- Include the exact source archive, signature, license text, public key, build script/configuration, and binary/source hashes in the Windows ZIP; fail closed on missing or mismatched material.
- Preserve manual workflow artifact upload and the existing tag-only Release condition; this task creates no tag or Release.
- Do not change OpenRouter models, ZDR language, key handling, or the audio-transcription protocol.

## Review Focus

- A source archive or signature downloaded with the wrong bytes must fail before configure/build; Task 1 tests the pinned hash and fail-closed cache/download path.
- A configure change must not silently enable GPL/nonfree/network functionality or disable needed app features; Task 1 tests the explicit build configuration and Task 3 smoke-tests WAV, M4A, OGG, and FLAC.
- Missing FFmpeg shared libraries, source, license, or hash provenance must prevent ZIP creation; Tasks 2–3 test required material validation and DLL collection.
- The minimal build must still inspect an M4A, detect quiet sections, and produce 16 kHz mono `pcm_s16le` WAV; Task 3 adds a generated-media Windows CI smoke test.
- Manual CI must upload a test artifact without publishing a Release, while a versioned tag still uses the existing Release path; Task 4 tests workflow conditions and artifact path.

---

### Task 1: Pin FFmpeg Source and Define the Minimal Windows Build

**Files:**
- Modify: `packaging/fetch_ffmpeg.py`
- Create: `packaging/build_ffmpeg.sh`
- Create: `packaging/ffmpeg-release-key.asc`
- Create: `tests/test_ffmpeg_source_build.py`
- Modify: `tests/test_build_release.py` (remove tests for the former prebuilt GPL binary downloader)

**Interfaces:**
- Produces `fetch(dest_dir: Path) -> tuple[Path, Path]`, returning the verified FFmpeg 9.0.2 source archive and its detached signature; source cache hits must be re-hashed against the pinned SHA before reuse.
- Produces a UCRT64 build command that stages `ffmpeg.exe`, `ffprobe.exe`, every generated FFmpeg runtime DLL, exact source/signature inputs, full license text, and build metadata under `packaging/bin/`.
- Consumes only the official source URL `https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz`; expected digest and signer fingerprint are the exact values in Global Constraints.

- [x] **Step 1: Write source-fetch tests first.** Cover a valid pinned source download, a cached archive whose digest is rechecked, a tampered archive rejected before it can be staged, and clear failure when download/signature assets are absent. Tests use mocked responses and no network.
- [x] **Step 2: Run tests to verify RED.** Run `PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/parth/Desktop/Code/audio-transcriber-app/.venv/bin/python -m pytest tests/test_ffmpeg_source_build.py -q`. Expected: feature failures, not import/fixture errors.
- [x] **Step 3: Implement the pinned source fetcher.** Download the `.tar.xz` and `.tar.xz.asc` to temporary files, validate the archive SHA-256 before atomic replacement, and never treat a mismatched cached archive as valid.
- [x] **Step 4: Write build-configuration tests before the build script.** Assert source version, key fingerprint/signature verification, LGPL-only flags (`--disable-gpl`, `--disable-version3`, `--disable-nonfree`, `--disable-network`, `--disable-autodetect`), shared libraries, MOV/MP3/WAV/FLAC/OGG demuxers, AAC/ALAC/MP3/FLAC/Vorbis/Opus/common PCM decoders, `silencedetect`, file protocol, WAV output, and needed AAC/Vorbis/FLAC smoke encoders/muxers. Run `bash -n` on the script.
- [x] **Step 5: Run configuration tests to verify RED.** Expected: missing build-script/configuration failures only.
- [x] **Step 6: Implement `packaging/build_ffmpeg.sh`.** Under MSYS2 UCRT64, verify the pinned SHA and GPG signature after checking the imported key's full fingerprint; configure/build/install FFmpeg 9.0.2 with the tested minimal LGPL shared-library feature set; stage all runtime DLLs and binaries; copy source, signature, key, `COPYING.LGPLv2.1`, and build scripts; emit source/build/binary hash metadata and a source-in-package offer. Disable automatic network protocols and external codec libraries.
- [x] **Step 7: Run Task 1 tests.** Expected: source-fetch, configuration-contract, and Bash-syntax tests pass.

### Task 2: Validate and Bundle FFmpeg Source, Build, and License Provenance

**Files:**
- Modify: `packaging/license_material.py`
- Modify: `tests/test_license_material.py`
- Modify: `LICENSES/README.md`
- Modify: `LICENSES/THIRD-PARTY-NOTICES.md`
- Modify: `LICENSES/FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md`
- Modify or delete: `packaging/ffmpeg-source-compliance/README.md`
- Test: `tests/test_build_release.py`

**Interfaces:**
- Consumes the build outputs and metadata placed in `packaging/bin/` by Task 1.
- Produces ZIP files under `AudioTranscriber/LICENSES/FFmpeg/`, including source archive/signature/key, build recipe, LGPL license, source offer, and verified metadata.
- `validate_release_license_material(license_dir: Path) -> None` rejects missing/placeholder material and mismatched hashes for source and staged runtime files.

- [x] **Step 1: Write failing license tests.** Replace BtbN/GPL fixtures with a valid source-built LGPL fixture; test successful collection, wrong source digest rejection, changed executable/DLL hash rejection, missing source/signature/license rejection, and ZIP inclusion of exact source/build materials.
- [x] **Step 2: Run focused tests to verify RED.** Run `PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/parth/Desktop/Code/audio-transcriber-app/.venv/bin/python -m pytest tests/test_license_material.py tests/test_build_release.py -q`. Expected: incompatibility with old BtbN requirements.
- [x] **Step 3: Replace BtbN provenance collection.** Stage only build-produced assets; validate pinned source digest, signature/fingerprint metadata, full LGPL text, build-script hash, and hashes of both executables and every FFmpeg DLL. Generate accurate LGPL/minimal-build notices; remove obsolete GPL blocker language without making an unreviewed legal guarantee.
- [x] **Step 4: Run focused tests to verify GREEN.** Expected: valid ZIP contents pass; absent/altered provenance fails before archive creation.

### Task 3: Package Shared FFmpeg Runtime and Prove App-Relevant Features

**Files:**
- Modify: `packaging/AudioTranscriber.spec`
- Create: `packaging/smoke_test_ffmpeg.py`
- Modify: `tests/test_build_release.py`
- Test: `tests/test_ffmpeg_source_build.py`

**Interfaces:**
- Consumes `packaging/bin/ffmpeg.exe`, `ffprobe.exe`, and all FFmpeg DLLs from Task 1.
- Produces an onedir distribution with executables and shared DLLs at the application root, alongside Task 2 license/source materials.
- Smoke-test CLI creates temporary synthetic WAV, round-trips AAC/M4A, Vorbis/OGG, and FLAC, probes outputs, runs silence detection, extracts canonical WAV, and verifies output properties. CI asserts MP3 decoder registration; no media is committed/uploaded.

- [x] **Step 1: Write failing PyInstaller spec tests.** Place several fixture DLLs in `packaging/bin/`; assert every DLL and both executables are collected at the app root and absent assets are not fabricated.
- [x] **Step 2: Run the test to verify RED.** Run `PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/parth/Desktop/Code/audio-transcriber-app/.venv/bin/python -m pytest tests/test_build_release.py::test_spec_collects_all_ffmpeg_shared_libraries -q`. Expected: DLLs absent from `Analysis.binaries`.
- [x] **Step 3: Update the PyInstaller spec.** Collect `ffmpeg.exe`, `ffprobe.exe`, and every `*.dll` from the FFmpeg staging directory as onedir root binaries.
- [x] **Step 4: Run the spec test to verify GREEN.** Expected: all fixture executables and DLLs collected at root.
- [x] **Step 5: Add and test the local FFmpeg smoke script.** On Windows CI, use temporary generated WAV only; verify WAV/M4A/OGG/FLAC probe/decode, MP3 decoder registration, silence filter, and output `pcm_s16le`, 16 kHz, mono via FFprobe.

### Task 4: Build and Upload a Windows Actions Test Artifact

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `tests/test_release_workflow.py`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-09-29-windows-audio-transcriber.md`

**Interfaces:**
- Consumes the source build, smoke test, PyInstaller package, and `AudioTranscriber.exe --self-test`.
- Manual dispatch uploads `AudioTranscriber-windows-test` containing `dist/AudioTranscriber-v<version>-win-x64.zip`; it does not publish a Release. Existing tag pushes keep the tag-only Release path.

- [x] **Step 1: Write failing workflow tests.** Assert Windows 2022/MSYS2 UCRT64 with MinGW/NASM; source build and synthetic smoke precede packaging; self-test follows packaging; manual artifact upload exists; Release remains tag-only; no secrets/audio paths are used.
- [x] **Step 2: Run tests to verify RED.** Run `PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/parth/Desktop/Code/audio-transcriber-app/.venv/bin/python -m pytest tests/test_release_workflow.py -q`. Expected: failures for missing MSYS2/build/artifact steps.
- [x] **Step 3: Update workflow and docs.** Add UCRT64 setup/build/smoke steps, preserve version validation and tag-only Release conditions, name the test artifact, and document that manual CI creates an Actions download but no Release. Record the FFmpeg source URL/hash/signature and minimal LGPL feature set.
- [x] **Step 4: Run full Linux suite and checks.** Run `PYTHONPATH=src QT_QPA_PLATFORM=offscreen /home/parth/Desktop/Code/audio-transcriber-app/.venv/bin/python -m pytest -q`, `bash -n packaging/build_ffmpeg.sh`, and `git diff --check`. Expected: suite green; Windows compilation is verified by CI, not Linux mocks.
- [ ] **Step 5: Commit on `feat/pinned-lgpl-ffmpeg`; do not create a tag or Release.** Before pushing the branch or dispatching Actions, obtain confirmation because those are external GitHub side effects. Once authorized, manually run workflow with version `0.1.0`, inspect the Windows build/self-test and artifact, and give the user its Actions link.
