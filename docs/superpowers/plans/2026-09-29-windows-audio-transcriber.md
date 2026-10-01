# Windows Audio Transcriber Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PySide6 Windows desktop app that transcribes an audio/video file through OpenRouter's STT endpoint with FFmpeg-based canonical WAV chunking, and ship it as a PyInstaller `--onedir` GitHub Release ZIP.

**Architecture:** A framework-agnostic core (credentials, model discovery, HTTP client, audio prep, chunk planning, transcript assembly, pipeline) is driven by a thin Qt UI layer that runs the pipeline on a worker thread. Every core module is testable without rendering a window or touching the network. FFmpeg is bundled; FFmpeg is invoked for probing, silence detection, and per-chunk extraction — never through a shell string.

**Tech Stack:** Python 3.11+, PySide6, httpx, keyring, FFmpeg/FFprobe binaries, pytest + pytest-qt, PyInstaller, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-29-windows-audio-transcriber-design.md`

## Global Constraints

These apply to every task. Do not deviate without changing the spec.

- Approved models are exactly `openai/whisper-large-v3-turbo` (default) and `openai/whisper-large-v3`. `openai/whisper-1` and `openai/text-embedding-3-large` must never appear in code, tests, or UI.
- Never send `provider.zdr` (or any `provider` field) on transcription requests. The STT endpoint does not support per-request data-policy enforcement.
- Never silently fall back to a different transcription model. If neither approved model is available, stop with an explanation.
- The app must never claim to verify or enforce ZDR. The string `ZDR must be enforced on this API key/account. The application cannot verify or enforce this for transcription.` must be displayed verbatim in the UI and README, and acknowledged before the first transcription.
- API key storage is Windows Credential Manager only, and must **fail closed** — never fall back to a plaintext file, env var, or registry blob.
- Never log the API key, audio bytes, or transcript text.
- Displayed cost comes only from the API's `usage.cost`. If it is absent, say unavailable. Never compute a local cost estimate and present it as fact.
- Canonical audio is 16 kHz, mono, signed 16-bit PCM WAV. No pass-through or source-format optimization in v1.
- Fixed chunk constants, defined once in `constants.py`, never exposed in the UI: `TARGET_CHUNK_SECONDS = 30`, `OVERLAP_SECONDS = 1`, `MAX_CONCURRENT_REQUESTS = 3`.
- Do not denoise, strip silence, compress, or otherwise alter speech content.
- Do not automatically retry timeouts, 408, 502, 503, or any ambiguous failure. Only 429 is auto-retried, with bounded backoff honoring `Retry-After`.
- Only deduplicate text at the boundary between chunk N and chunk N+1. Never remove repeated phrases elsewhere in the transcript.
- The original input file is never modified.
- No API key, sample recording, transcript, or generated WAV is committed or uploaded by CI.
- Test commands run from the repo root and must exit 0.

## Review Focus

The spec implies these conditions that no requirement directly names. Each has a test pinned to the task that owns the code.

1. **A file with no audio stream** (video-only, or a corrupt file ffprobe can barely parse) — the user gets a clear "no audio stream" message; no chunking runs and no API call is made.
2. **Degenerate durations** — a recording shorter than the overlap, and one whose length is an exact multiple of the chunk stride — neither produces a zero-length, duplicate, or start-past-end chunk.
3. **A chunk that is pure silence** returns empty `text` — it is a success, contributes nothing to the transcript, and does not crash or corrupt boundary deduplication.
4. **Cancellation during a long run** — no further chunks are scheduled, the workspace temp directory is removed, and the partial transcript plus failure list remain available.
5. **A sustained 429 during a long recording** — retries are bounded, `Retry-After` is honored, and when the budget is exhausted the run stops with a readable error and a partial transcript rather than looping forever.

---

## File Structure

```
pyproject.toml                  # deps, pytest config, entry point
README.md                       # user-facing download/run/ZDR docs
.gitignore
LICENSES/README.md              # third-party license index (filled in Task 11)
src/audio_transcriber/
  __init__.py                   # package marker + __version__
  __main__.py                   # --self-test dispatch, else launch GUI
  constants.py                  # frozen numeric + text constants; single source of truth
  errors.py                     # exception hierarchy, each carrying user_message
  credentials.py                # Windows Credential Manager, fail-closed
  openrouter_client.py          # httpx client: model discovery + transcription
  audio.py                      # ffmpeg/ffprobe process wrappers (probe, silence, extract)
  chunking.py                   # pure chunk planning + quiet-point snapping
  workdir.py                    # temp workspace lifecycle + stale cleanup
  transcript.py                 # boundary dedup + ordered assembly
  pipeline.py                   # concurrency, progress, retry, cancellation, reporting
  selftest.py                   # headless Qt + FFmpeg verification
  ui/__init__.py
  ui/app.py                     # QApplication bootstrap
  ui/key_dialog.py              # key entry + ZDR disclaimer
  ui/main_window.py             # main window and worker-thread wiring
tests/                          # mirrors src/ layout, one test module per source module
packaging/
  AudioTranscriber.spec         # PyInstaller onedir spec
  fetch_ffmpeg.py               # fetch and verify pinned FFmpeg source/signature
  build_ffmpeg.sh               # source-build FFmpeg in MSYS2 UCRT64
  smoke_test_ffmpeg.py          # synthetic-media runtime feature test
  build_release.py              # onedir build + zip
.github/workflows/release.yml   # test, source-build, package, self-test, artifact/release
```

---

### Task 1: Package Scaffold, Constants, and Error Hierarchy

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/audio_transcriber/__init__.py`
- Create: `src/audio_transcriber/constants.py`
- Create: `src/audio_transcriber/errors.py`
- Test: `tests/test_constants.py`, `tests/test_errors.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `constants.TARGET_CHUNK_SECONDS` (int, `30`), `constants.OVERLAP_SECONDS` (int, `1`), `constants.MAX_CONCURRENT_REQUESTS` (int, `3`), `constants.ALLOWED_MODELS` (tuple[str, str], turbo first), `constants.DEFAULT_MODEL` (str), `constants.ZDR_WARNING` (str, verbatim spec text), `constants.OPENROUTER_BASE_URL` (str, `"https://openrouter.ai/api/v1"`), `constants.CANONICAL_SAMPLE_RATE` (`16000`), `constants.CANONICAL_CHANNELS` (`1`), `constants.CANONICAL_FORMAT` (`"wav"`), `constants.MAX_RATE_LIMIT_RETRIES` (`3`), `constants.RETRY_BASE_DELAY_SECONDS` (`2.0`), `constants.LANGUAGES` (tuple[str, ...]), `errors.TranscriberError` (base, `.user_message` on every instance).

- [ ] **Step 1: Write the failing tests**

`tests/test_constants.py` — assert the spec's pinned values exactly, so a future edit that changes 30/1/3 or the model list fails loudly:

```python
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
```

`tests/test_errors.py` — every exception carries a non-empty, human-readable `user_message` and none of them mention the key's value:

```python
def test_every_error_has_a_readable_message():
    for name in errors.EXPORTED_ERRORS:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.TranscriberError)
        assert cls("boom").user_message.strip()

def test_ambiguous_failures_are_flagged_not_retryable():
    assert errors.RequestTimeoutError("t").retryable is False
    assert errors.ProviderError("p").retryable is False
    assert errors.RateLimitError("r").retryable is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_constants.py tests/test_errors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber'`

- [ ] **Step 3: Create `pyproject.toml`**

Use a `src` layout with `[project] requires-python = ">=3.11"`, dependencies `pyside6`, `httpx>=0.27`, `keyring>=25`; optional-dependencies `dev` = `pytest`, `pytest-qt`, and `packaging` = `pyinstaller>=6`. Configure `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `[tool.setuptools.packages.find] where = ["src"]`. Add `[project.scripts] audio-transcriber = "audio_transcriber.__main__:main"`.

- [ ] **Step 4: Implement `constants.py` and `errors.py`**

`constants.py` holds only module-level constants — no imports beyond `typing`.

`errors.py` defines the hierarchy. Each class sets `user_message` to the literal text a non-technical user should read, and `retryable` is `False` by default:

| Class | Base | `retryable` | `user_message` intent |
|---|---|---|---|
| `TranscriberError` | `Exception` | `False` | generic fallback |
| `CredentialStoreUnavailable` | `TranscriberError` | `False` | secure storage unavailable; do not proceed |
| `FfmpegMissingError` | `TranscriberError` | `False` | FFmpeg/FFprobe not found next to the app or on PATH |
| `AudioPreparationError` | `TranscriberError` | `False` | audio could not be prepared |
| `NoAudioStreamError` | `AudioPreparationError` | `False` | file contains no audio track |
| `ModelDiscoveryError` | `TranscriberError` | `False` | model list could not be fetched |
| `NoApprovedModelAvailable` | `ModelDiscoveryError` | `False` | neither approved model available under this key |
| `ApiError` | `TranscriberError` | `False` | provider returned an error; carries `.status_code` |
| `AuthenticationError` | `ApiError` | `False` | key invalid |
| `InsufficientCreditsError` | `ApiError` | `False` | account/key out of credits |
| `ForbiddenError` | `ApiError` | `False` | blocked by key/account restrictions |
| `InvalidRequestError` | `ApiError` | `False` | bad audio or unsupported request |
| `RateLimitError` | `ApiError` | `True` | rate limited; carries `.retry_after: float \| None` |
| `RequestTimeoutError` | `ApiError` | `False` | timed out; may already be billed |
| `ProviderError` | `ApiError` | `False` | upstream provider failed; may already be billed |
| `CancelledError` | `TranscriberError` | `False` | run cancelled |

Add `__all__` and a module-level `EXPORTED_ERRORS` tuple listing every public error class name, which Step 1's test iterates.

- [ ] **Step 5: Create `.gitignore`**

Ignore `__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `build/`, `*.spec.bak`, `packaging/bin/`, `.pytest_cache/`, and `.serena/`. Do **not** ignore `packaging/AudioTranscriber.spec`.

- [ ] **Step 6: Create `__init__.py`**

Expose `__version__ = "0.1.0"` only. No imports of submodules, so importing the package never pulls in Qt or httpx.

- [ ] **Step 7: Install the package and run the tests**

Run: `python -m pip install -e ".[dev]" -q && python -m pytest tests/ -v`
Expected: PASS — all tests in both files pass.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml .gitignore src/audio_transcriber/ tests/
git commit -m "feat: scaffold package with pinned constants and error hierarchy"
```

---

### Task 2: Windows Credential Manager Storage

**Files:**
- Create: `src/audio_transcriber/credentials.py`
- Test: `tests/test_credentials.py`

**Interfaces:**
- Consumes: `errors.CredentialStoreUnavailable` from Task 1.
- Produces:
  - `credentials.SERVICE_NAME: str` (`"AudioTranscriber"`)
  - `credentials.ACCOUNT_NAME: str` (`"openrouter_api_key"`)
  - `class CredentialStore` with `__init__(self, backend: KeyringBackend | None = None)`, `.backend_name: str`, `.load() -> str | None`, `.save(key: str) -> None`, `.forget() -> None`.
  - `class KeyringBackend(Protocol)`: `.get_password(service, username) -> str | None`, `.set_password(service, username, password) -> None`, `.delete_password(service, username) -> None`.

- [ ] **Step 1: Write the failing tests**

Use a `FakeBackend` recording calls. Cover the four behaviors the spec depends on — Review Focus item: fail closed, no plaintext fallback, no management-key distinction in storage, and key never echoed:

```python
class FakeBackend:
    def __init__(self, stored=None):
        self.stored = stored
        self.calls = []
    def get_password(self, service, username):
        self.calls.append(("get", service, username)); return self.stored
    def set_password(self, service, username, password):
        self.calls.append(("set", service, username)); self.stored = password
    def delete_password(self, service, username):
        self.calls.append(("delete", service, username)); self.stored = None

def test_missing_key_returns_none():
    assert CredentialStore(FakeBackend()).load() is None

def test_save_then_load_round_trips():
    backend = FakeBackend()
    CredentialStore(backend).save("sk-or-v1-secret")
    assert CredentialStore(backend).load() == "sk-or-v1-secret"

def test_forget_deletes_the_credential():
    backend = FakeBackend(stored="sk-or-v1-secret")
    CredentialStore(backend).forget()
    assert CredentialStore(backend).load() is None

def test_rejects_empty_or_whitespace_key():
    with pytest.raises(ValueError):
        CredentialStore(FakeBackend()).save("   ")

def test_unavailable_backend_fails_closed_without_writing_anywhere(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(CredentialStoreUnavailable):
        CredentialStore(backend=None, require_windows_backend=True).save("sk-or-v1-secret")
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.credentials'`

- [ ] **Step 3: Implement `credentials.py`**

`CredentialStore.__init__(self, backend=None, require_windows_backend=True)`. When `backend` is `None`, resolve via `keyring.get_keyring()`. Security rule, enforced in the constructor and re-checked before every operation:

```python
def _is_windows_backend(backend) -> bool:
    cls = type(backend)
    return getattr(cls, "__module__", "").startswith("keyring.backends.Windows")
```

If `require_windows_backend` is true and the resolved backend is not the Windows backend, raise `CredentialStoreUnavailable` with a `user_message` telling the user the app only stores keys in Windows Credential Manager. Never catch this and fall back.

`save` rejects `""` and whitespace-only input with `ValueError`. `load` returns `None` for missing credentials but converts a backend exception into `CredentialStoreUnavailable`. `forget` tolerates an already-absent credential and raises `CredentialStoreUnavailable` if the backend itself fails. Add no logging, and no `__repr__` that could leak a stored value.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_credentials.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS — no regressions in Tasks 1's tests.

- [ ] **Step 6: Commit**

```bash
git add src/audio_transcriber/credentials.py tests/test_credentials.py
git commit -m "feat: store API key in Windows Credential Manager with fail-closed behavior"
```

---

### Task 3: OpenRouter Client — Transport, Error Mapping, Model Discovery

**Files:**
- Create: `src/audio_transcriber/openrouter_client.py`
- Test: `tests/test_openrouter_client.py`

**Interfaces:**
- Consumes: `constants.OPENROUTER_BASE_URL`, `constants.ALLOWED_MODELS` from Task 1; error classes from Task 1.
- Produces:
  - `class OpenRouterClient` with `__init__(self, api_key: str, *, transport: httpx.BaseTransport | None = None, timeout: float = 60.0)`, `.list_available_models() -> list[str]`, `.transcribe(wav_path: Path, model: str, language: str | None = None) -> TranscriptionResponse`, `.close()`, and context-manager support.
  - `class TranscriptionResponse(NamedTuple)`: `text: str`, `usage: Usage | None`, `generation_id: str | None`.
  - `class Usage(NamedTuple)`: `seconds: float | None`, `total_tokens: int | None`, `input_tokens: int | None`, `output_tokens: int | None`, `cost: float | None`.

- [ ] **Step 1: Write the failing tests**

Drive every case through `httpx.MockTransport` so nothing touches the network. Include Review Focus item 5 (bounded retry is Task 8's job, but `RateLimitError.retry_after` parsing is pinned here):

```python
def _client(handler) -> OpenRouterClient:
    return OpenRouterClient("sk-or-v1-test", transport=httpx.MockTransport(handler))

def test_discovery_returns_allowlisted_models_in_allowlist_order():
    def handler(request):
        assert request.url.path == "/api/v1/models/user"
        assert request.url.params["output_modalities"] == "transcription"
        return httpx.Response(200, json={"data": [
            {"id": "openai/whisper-large-v3"},
            {"id": "openai/whisper-1"},
            {"id": "openai/whisper-large-v3-turbo"},
        ]})
    assert _client(handler).list_available_models() == [
        "openai/whisper-large-v3-turbo", "openai/whisper-large-v3",
    ]
```

Plus tests for: `401` → `AuthenticationError`; `402` → `InsufficientCreditsError`; `403` → `ForbiddenError`; `429` with `Retry-After: 30` → `RateLimitError` with `retry_after == 30.0`; `429` without the header → `RateLimitError` with `retry_after is None`; `502` → `ProviderError`; `408` → `RequestTimeoutError`; a malformed body → the corresponding error rather than a raw `json.JSONDecodeError`. Also assert the `Authorization` header is `Bearer sk-or-v1-test` and that the key never appears in any error's `user_message`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_openrouter_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.openrouter_client'`

- [ ] **Step 3: Implement the client skeleton and discovery**

`__init__` builds `httpx.Client(base_url=constants.OPENROUTER_BASE_URL, timeout=timeout, transport=transport, headers={"Authorization": f"Bearer {api_key}"})`. `list_available_models` GETs `/models/user` with params `{"output_modalities": "transcription"}`, reads `response.json()["data"]`, collects `entry["id"]`, intersects with `constants.ALLOWED_MODELS`, and returns the result **in `ALLOWED_MODELS` order** (turbo first), de-duplicated. It raises `ModelDiscoveryError` for any non-200 that is not already mapped, and it must not send or accept any fallback model.

- [ ] **Step 4: Implement the error-mapping helper and `transcribe`**

Add a private `_raise_for_status(response: httpx.Response) -> None` used by both endpoints. It reads `response.json().get("error", {})` defensively (fall back to `{}` on a non-JSON body), maps by `response.status_code` using the table below, and sets `retry_after` on `RateLimitError` from a numeric `Retry-After` header.

| Status | Raised |
|---|---|
| 400 | `InvalidRequestError` |
| 401 | `AuthenticationError` |
| 402 | `InsufficientCreditsError` |
| 403 | `ForbiddenError` |
| 408 | `RequestTimeoutError` |
| 429 | `RateLimitError` |
| 502, 503 | `ProviderError` |

Other statuses raise `ApiError`. Every message passed into these constructors is a fixed, status-appropriate string — never the raw response body, so no transcript or key material can leak into a message.

`transcribe` reads `wav_path.read_bytes()`, base64-encodes to ASCII, and POSTs to `/audio/transcriptions` with exactly this JSON body and nothing else:

```json
{"model": "<id>", "input_audio": {"data": "<base64>", "format": "wav"}}
```

Omit `language` entirely when `None`. Add `temperature: 0` for determinism. **Never** include a `provider` key. Wrap `httpx.TimeoutException` as `RequestTimeoutError`. Parse the response into `TranscriptionResponse`, reading `usage` only if present and coercing each field independently — a missing `cost` yields `usage.cost is None`, never `0`. Read `X-Generation-Id` from response headers, defaulting to `None`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_openrouter_client.py -v`
Expected: PASS

- [ ] **Step 6: Verify the request shape has no `provider` key**

Run: `python -m pytest tests/test_openrouter_client.py -k transcribe -v`
Expected: PASS, and the test asserting `assert "provider" not in sent_body` passes.

- [ ] **Step 7: Commit**

```bash
git add src/audio_transcriber/openrouter_client.py tests/test_openrouter_client.py
git commit -m "feat: add OpenRouter client with model discovery and error mapping"
```

---

### Task 4: FFmpeg Discovery, Probing, and Silence Detection

**Files:**
- Create: `src/audio_transcriber/audio.py`
- Test: `tests/test_audio.py`

**Interfaces:**
- Consumes: `errors.FfmpegMissingError`, `errors.NoAudioStreamError`, `errors.AudioPreparationError` from Task 1; `constants.CANONICAL_SAMPLE_RATE`.
- Produces:
  - `class MediaInfo(NamedTuple)`: `duration: float`, `has_audio: bool`, `format_name: str`, `codec_name: str | None`, `sample_rate: int | None`, `channels: int | None`.
  - `resolve_binary(name: str, *, bundled_dir: Path | None = None) -> Path` — searches `bundled_dir` (when frozen, the directory containing the executable) then `shutil.which(name)`; raises `FfmpegMissingError` if neither yields an executable.
  - `probe(source: Path, *, ffprobe: Path | None = None, cancel_event: Event | None = None, timeout: float = ...) -> MediaInfo`
  - `detect_quiet_midpoints(..., cancel_event: Event | None = None, timeout: float = ...) -> list[float]` — bounded and cancellable, returning ascending silence midpoints.
  - `extract_chunk(..., cancel_event: Event | None = None, timeout: float = ...) -> Path` — bounded and cancellable; writes canonical WAV and reaps its child on cancellation.

- [ ] **Step 1: Write the failing tests**

Most tests inject a fake ffprobe/ffmpeg script. Two tests are **skipped** unless a real `ffmpeg` is on `PATH` (marker: `@pytest.mark.skipif(shutil.which("ffmpeg") is None, ...)`), and they synthesize their own audio with `ffmpeg -f lavfi -i sine=...` so no personal media is required:

```python
def test_probe_reports_duration_and_audio_stream(tmp_path, real_ffmpeg):
    media = make_sine_wav(tmp_path / "tone.wav", seconds=5)
    info = probe(media)
    assert info.has_audio is True
    assert info.duration == pytest.approx(5.0, abs=0.3)
```

```python
def test_extract_chunk_produces_canonical_wav(tmp_path, real_ffmpeg):
    media = make_sine_wav(tmp_path / "tone.wav", seconds=10)
    out = extract_chunk(media, start=2.0, duration=3.0, out_path=tmp_path / "c0.wav")
    assert out.exists()
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                              "stream=sample_rate,channels,codec_name",
                              "-of", "json", str(out)], capture_output=True, text=True, check=True)
    stream = json.loads(result.stdout)["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert stream["sample_rate"] == "16000"
    assert stream["channels"] == "1"
```

The remaining tests use fake executables: `test_probe_raises_no_audio_stream_for_video_only_input`, `test_probe_raises_on_unparseable_output`, `test_resolve_binary_prefers_bundled_directory`, `test_resolve_binary_falls_back_to_path`, `test_resolve_binary_raises_when_missing`, and a Review-Focus-1 test `test_detect_quiet_midpoints_returns_sorted_midpoints` asserting the parsed list is sorted and within the media duration.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_audio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.audio'`

- [ ] **Step 3: Implement `resolve_binary`**

When `sys.frozen` is true, default `bundled_dir` to `Path(sys.executable).parent`; otherwise `None`. Search `bundled_dir / (name + ".exe")` and `bundled_dir / name` first, then `shutil.which(name)`. Raise `FfmpegMissingError` with a `user_message` that names the missing binary and tells the user to re-download the release ZIP.

- [ ] **Step 4: Implement `probe`**

Run `ffprobe -v error -print_format json -show_format -show_streams <source>` via a shared `Popen` helper using an argument list and finite deadline. Poll the cancellation event; on cancel/timeout terminate, wait briefly, kill if necessary, and reap. On a non-zero return code or unparseable JSON, raise `AudioPreparationError`. If no audio stream exists, raise `NoAudioStreamError`.

- [ ] **Step 5: Implement `detect_quiet_midpoints`**

Run the silence scan through the same cancellable, time-bounded process helper; parse silence events as before. Propagate cancellation and report timeouts as readable `AudioPreparationError`s.

- [ ] **Step 6: Implement `extract_chunk`**

Run extraction through the same cancellable, time-bounded helper. Create `out_path.parent` if needed. On timeout or non-zero return code, raise `AudioPreparationError` with a short, key-free summary. Add no denoise, volume, or silence filters. Do not delete or modify the source.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_audio.py -v`
Expected: PASS — the two real-FFmpeg tests run (ffmpeg is present) and the rest pass.

- [ ] **Step 8: Commit**

```bash
git add src/audio_transcriber/audio.py tests/test_audio.py
git commit -m "feat: add ffmpeg probing, silence detection, and canonical WAV extraction"
```

---

### Task 5: Chunk Planning with Quiet-Point Snapping

**Files:**
- Create: `src/audio_transcriber/chunking.py`
- Test: `tests/test_chunking.py`

**Interfaces:**
- Consumes: `constants.TARGET_CHUNK_SECONDS`, `constants.OVERLAP_SECONDS` from Task 1.
- Produces:
  - `class ChunkSpan(NamedTuple)`: `index: int`, `start: float`, `end: float`, with `@property duration`.
  - `plan_chunks(duration: float, quiet_midpoints: Sequence[float] = (), *, target: int = constants.TARGET_CHUNK_SECONDS, overlap: int = constants.OVERLAP_SECONDS, search_window: float = 1.5) -> list[ChunkSpan]` — pure, deterministic, no I/O.

- [ ] **Step 1: Write the failing tests**

This is the highest-risk logic in the project, so cover the boundaries exhaustively, including Review Focus item 2:

```python
def test_short_recording_is_a_single_chunk():
    spans = plan_chunks(20.0)
    assert [(s.start, s.end) for s in spans] == [(0.0, 20.0)]

def test_recording_shorter_than_overlap_window_is_one_chunk():
    spans = plan_chunks(1.5)
    assert len(spans) == 1 and spans[0].end == 1.5

def test_nominal_spans_use_target_duration_and_overlap():
    spans = plan_chunks(100.0)
    assert [(s.start, s.end) for s in spans] == [
        (0.0, 30.0), (29.0, 59.0), (58.0, 88.0), (87.0, 100.0)
    ]

def test_exact_multiple_of_stride_produces_no_empty_trailing_chunk():
    spans = plan_chunks(116.0)   # 4 chunks of 30s at stride 29 exactly covers 0..116
    assert all(s.end > s.start for s in spans)
    assert all(s.duration <= 30.0 + 1e-9 for s in spans)
    assert spans[-1].end == pytest.approx(116.0)

@pytest.mark.parametrize("duration", [30.0, 30.5, 31.0, 31.5, 58.0, 59.0, 300.0, 900.0])
def test_spans_are_always_well_formed(duration):
    spans = plan_chunks(duration)
    assert spans[0].start == 0.0
    assert spans[-1].end == pytest.approx(duration)
    for i, span in enumerate(spans):
        assert 0.0 <= span.start < span.end <= duration
        assert span.duration <= (duration if duration <= 31.0 else 30.0) + 1e-9
        assert span.index == i
    for a, b in zip(spans, spans[1:]):
        assert b.start <= a.end         # no source audio is omitted
        assert a.end - b.start == pytest.approx(1.0, abs=1e-6)
```

Add snapping tests: `test_boundary_snaps_to_nearest_quiet_point_within_window`, `test_boundary_outside_window_is_left_alone`, `test_snapping_preserves_strictly_increasing_starts`, a near-end point inside the 1.5-second search window, and an adversarial opposing-snap case proving continuous source coverage.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_chunking.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.chunking'`

- [ ] **Step 3: Implement `plan_chunks`**

Algorithm, in order:

1. If `duration <= target + overlap`, return `[ChunkSpan(0, 0.0, duration)]`.
2. Begin at zero. For each span choose `end = min(start + target, duration)` and, only when `end < duration`, snap that end to the nearest quiet midpoint within `search_window`; ties break toward the earlier midpoint. Do not snap beyond the target duration or allow a snap to prevent forward progress.
3. Append the span. If its end is before the source duration, set the next start to `end - overlap` and repeat.
4. Re-index spans in order. Deriving each start from the prior end guarantees gap-free coverage and approximately one-second overlap despite opposing quiet-point snaps.

No randomness, no clock reads, no file access.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_chunking.py -v`
Expected: PASS

- [ ] **Step 5: Sanity-check against the real sample duration**

Run: `python -c "from audio_transcriber.chunking import plan_chunks; s=plan_chunks(6247.155729); print(len(s), s[0], s[-1])"`
Expected: a chunk count around 210, first span `(0, 0.0, 30.0)`, last span ending at `6247.155729`.

- [ ] **Step 6: Commit**

```bash
git add src/audio_transcriber/chunking.py tests/test_chunking.py
git commit -m "feat: plan fixed chunk spans with quiet-point boundary snapping"
```

---

### Task 6: Transcript Assembly with Boundary-Only Deduplication

**Files:**
- Create: `src/audio_transcriber/transcript.py`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Consumes: `constants` MIN/MAX dedup token bounds.
- Produces:
  - `constants.MIN_BOUNDARY_DEDUP_TOKENS: int` (`3`), `constants.MAX_BOUNDARY_DEDUP_TOKENS: int` (`20`).
  - `class TranscriptAssembler`: `__init__(self)`, `.add(index: int, text: str) -> None`, `.text() -> str`, `.covered_indices() -> set[int]`.
  - `dedupe_boundary(previous: str, incoming: str, *, min_tokens: int = MIN_BOUNDARY_DEDUP_TOKENS, max_tokens: int = MAX_BOUNDARY_DEDUP_TOKENS) -> str` — returns `incoming` with the boundary duplicate removed, or `incoming` unchanged.

- [ ] **Step 1: Write the failing tests**

Cover Review Focus item 3 (empty chunk) and the "never global" rule:

```python
def test_exact_boundary_repetition_is_removed():
    assert dedupe_boundary("so we said hello there", "there and then we left") == "and then we left"

def test_no_match_keeps_the_full_incoming_text():
    assert dedupe_boundary("alpha beta gamma", "delta epsilon") == "delta epsilon"

def test_short_overlap_below_minimum_is_kept():
    # only 2 tokens repeat; MIN_BOUNDARY_DEDUP_TOKENS is 3, so keep both
    assert dedupe_boundary("we said ok", "ok then") == "ok then"

def test_partial_token_match_is_kept():
    assert dedupe_boundary("that is the plan", "plan for later") == "plan for later"

def test_repeated_phrase_inside_the_incoming_text_is_not_removed():
    incoming = "we said ok then we said ok then we left"
    assert dedupe_boundary("completely different prefix", incoming) == incoming
```

Assembly tests: `test_assembly_is_ordered_by_index_regardless_of_insertion_order`, `test_empty_chunk_contributes_nothing`, `test_all_empty_chunks_produce_empty_string`, and `test_assembler_deduplicates_only_at_join_points` (three chunks where the same 4-word phrase appears at the start of chunk 1 and inside chunk 2 — it must survive).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_transcript.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.transcript'`

- [ ] **Step 3: Add the two constants**

Append `MIN_BOUNDARY_DEDUP_TOKENS = 3` and `MAX_BOUNDARY_DEDUP_TOKENS = 20` to `constants.py`, and a test in `tests/test_constants.py` asserting both values.

- [ ] **Step 4: Implement `dedupe_boundary`**

Tokenize with `re.findall(r"\S+", text)`. Compare `previous_tokens[-k:]` against `incoming_tokens[:k]` for `k` from `min(len(previous_tokens), len(incoming_tokens), max_tokens)` down to `min_tokens`, using a normalized comparison (casefold, then strip leading/trailing punctuation from each token). Return on the **first** `k` that matches: `" ".join(incoming_tokens[k:])`. If none match, or `incoming` is empty/whitespace, return `incoming` unchanged.

- [ ] **Step 5: Implement `TranscriptAssembler`**

Keep `self._chunks: dict[int, str]`. `add` stores the raw chunk text. `text()` walks indices in ascending order; for each one after the first, call `dedupe_boundary(previous_joined_tail, chunk_text)` and append the result; join non-empty results with a single space. Skip indices with empty text entirely so a silent chunk leaves no stray separator (Review Focus item 3).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_transcript.py tests/test_constants.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/audio_transcriber/transcript.py src/audio_transcriber/constants.py tests/test_transcript.py tests/test_constants.py
git commit -m "feat: assemble ordered transcripts with boundary-only deduplication"
```

---

### Task 7: Temporary Workspace Lifecycle

**Files:**
- Create: `src/audio_transcriber/workdir.py`
- Test: `tests/test_workdir.py`

**Interfaces:**
- Consumes: nothing beyond the stdlib.
- Produces:
  - `WORKSPACE_PREFIX: str` (`"audio-transcriber-"`)
  - `class AudioWorkspace` — context manager with `__init__(self, root: Path | None = None)`, `.path: Path`, `.chunk_path(index: int) -> Path`, `.cleanup() -> None` (idempotent).
  - `cleanup_stale_workspaces(root: Path | None = None) -> int` — removes only app-owned workspace directories with valid metadata whose owner PID is demonstrably stale; returns the count removed.

- [ ] **Step 1: Write the failing tests**

```python
def test_workspace_is_created_and_removed(tmp_path):
    with AudioWorkspace(root=tmp_path) as ws:
        assert ws.path.is_dir()
        assert ws.path.name.startswith(WORKSPACE_PREFIX)
        assert ws.chunk_path(3).name == "chunk_0003.wav"
        saved = ws.path
    assert not saved.exists()

def test_cleanup_is_idempotent(tmp_path):
    ws = AudioWorkspace(root=tmp_path)
    path = ws.path            # public access creates the directory lazily
    assert path.is_dir()
    ws.cleanup(); ws.cleanup()
    assert not path.exists()

def test_cleanup_stale_only_touches_our_prefix(tmp_path):
    keep = tmp_path / "someone-elses-data"; keep.mkdir()
    stale = tmp_path / (WORKSPACE_PREFIX + "old"); stale.mkdir()
    write_owner(stale, pid=DEAD_PID)
    assert cleanup_stale_workspaces(tmp_path) == 1
    assert keep.is_dir() and not stale.exists()

def test_cleanup_preserves_two_active_owners_and_permission_unknown_owner(tmp_path):
    # Current process owns two live workspaces; an unknown PID state is preserved.
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_workdir.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.workdir'`

- [ ] **Step 3: Implement `workdir.py`**

`AudioWorkspace` uses `tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=root)` lazily and writes an owner marker with application identity and PID. `cleanup()` remains idempotent. `cleanup_stale_workspaces` rejects symlinks and removes only matching directories with valid ownership metadata and a PID conclusively reported absent. Active, permission-denied, unknown, malformed, and unowned workspaces are preserved. Normal GUI startup calls cleanup before constructing the window.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_workdir.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/audio_transcriber/workdir.py tests/test_workdir.py
git commit -m "feat: manage and clean up the temporary audio workspace"
```

---

### Task 8: Transcription Pipeline

**Files:**
- Create: `src/audio_transcriber/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `openrouter_client.OpenRouterClient`, `.transcribe`, `TranscriptionResponse` (Task 3); `audio.probe`, `detect_quiet_midpoints`, `extract_chunk` (Task 4); `chunking.plan_chunks`, `ChunkSpan` (Task 5); `workdir.AudioWorkspace` (Task 7); `transcript.TranscriptAssembler` (Task 6); all errors and constants from Tasks 1/2.
- Produces:
  - `class ChunkOutcome(NamedTuple)`: `index: int`, `text: str`, `usage: Usage | None`, `generation_id: str | None`.
  - `class PipelineCallbacks`: methods `on_analyzing()`, `on_planned(total: int)`, `on_chunk_started(index: int, total: int)`, `on_chunk_finished(outcome: ChunkOutcome)`, `on_chunk_failed(index: int, error: TranscriberError)`, `on_finished(report: TranscriptionReport)`, `on_cancelled(report: TranscriptionReport)`. Default no-op implementations so callers override only what they need.
  - `class TranscriptionReport`: `.results: dict[int, ChunkOutcome]`, `.failures: dict[int, TranscriberError]`, `.total_chunks: int`, `.cancelled: bool`, `.is_complete: bool` (property), `.transcript() -> str`, `.total_cost() -> float | None`, `.total_seconds() -> float | None`, `.cost_note() -> str`.
  - `class TranscriptionPipeline`: `__init__(self, client: OpenRouterClient, *, model: str, callbacks: PipelineCallbacks | None = None, ffmpeg: Path | None = None, ffprobe: Path | None = None, workspace: AudioWorkspace | None = None, sleep_fn: Callable[[float], None] = time.sleep)`, `.run(source: Path, *, language: str | None = None) -> TranscriptionReport`, `.cancel() -> None`, `.retry_failed() -> TranscriptionReport`.

- [ ] **Step 1: Write the failing tests**

Inject a `FakeClient` with a controllable `transcribe`, a `sleep_fn` that records requested delays instead of sleeping, and a real `AudioWorkspace` under `tmp_path`. Define two module-level helpers so each test stays to three lines: a `tmp_media` fixture that synthesizes a 20-second sine WAV with ffmpeg, and `run_one_shot(client, media, **kwargs) -> TranscriptionReport` that builds a pipeline, runs it, and returns the report. Use the synthesized WAV so no personal audio is required. Cover Review Focus items 4 and 5:

```python
def test_report_total_cost_is_none_when_any_chunk_omits_cost(fake_client_partial_cost, tmp_media):
    report = run_one_shot(fake_client_partial_cost, tmp_media)
    assert report.total_cost() is None
    assert "unavailable" in report.cost_note().lower()

def test_report_total_cost_sums_when_all_chunks_report(fake_client_full_cost, tmp_media):
    assert run_one_shot(fake_client_full_cost, tmp_media).total_cost() == pytest.approx(0.003)

def test_cancelled_run_keeps_partial_results_and_removes_workspace(blocking_client, tmp_media, tmp_path):
    # blocking_client parks chunk 1 on a threading.Event; start run() on a thread,
    # wait for chunk 0, call pipeline.cancel(), join, then assert:
    #   report.cancelled is True
    #   0 in report.results
    #   the workspace directory no longer exists

def test_rate_limit_is_retried_with_retry_after_then_succeeds(flaky_client, tmp_media):
    # flaky_client returns 429 Retry-After: 0 twice, then 200; assert the run
    # completes and recorded_sleeps contains two entries

def test_rate_limit_budget_exhausted_stops_the_run_with_a_partial_report(always_429_client, tmp_media):
    # assert the run terminates, report.failures is non-empty,
    # report.cancelled is False, and the failure is a RateLimitError

def test_timeout_is_not_retried(timeout_client, tmp_media):
    # one RequestTimeoutError; assert exactly one client call was made

def test_results_are_assembled_in_index_order_not_completion_order(out_of_order_client, tmp_media):
    # chunk 2 completes before chunk 1; assert transcript order is 0,1,2

def test_retry_failed_resubmits_only_failed_chunks(flaky_client, tmp_media):
    # after one run, call pipeline.retry_failed(); assert the only newly
    # attempted index is the failed one
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.pipeline'`

- [ ] **Step 3: Implement `TranscriptionReport`**

`transcript()` builds a `TranscriptAssembler`, feeds `results` in ascending index order, and returns `assembler.text()`. `total_cost()` returns `None` if `results` is empty or if **any** outcome has `usage is None` or `usage.cost is None`; otherwise it sums the costs. `total_seconds()` follows the same all-or-nothing rule over `usage.seconds`. `cost_note()` returns a plain sentence for the display — e.g. `"Total cost reported by OpenRouter: $0.0030"` or `"Cost unavailable: OpenRouter did not report a cost for every chunk."`

- [ ] **Step 4: Implement `run` — the sequential preparation phase**

In order: `callbacks.on_analyzing()`; `info = probe(source, ffprobe=..., cancel_event=self._cancel_event)` (propagates `NoAudioStreamError`, satisfying Review Focus item 1); `quiet = detect_quiet_midpoints(..., cancel_event=self._cancel_event)`; `spans = plan_chunks(info.duration, quiet)`; `callbacks.on_planned(len(spans))`. Chunk extraction happens lazily inside each worker and receives the same cancellation event. FFmpeg children have finite deadlines and are terminated/reaped on cancel. Cancellation during preparation returns a cancelled report and still cleans the workspace.

- [ ] **Step 5: Implement `run` — the concurrent phase**

Submit every span to a `ThreadPoolExecutor(max_workers=constants.MAX_CONCURRENT_REQUESTS)`. Each worker: if the cancel event is set, return without extracting or requesting; otherwise extract the chunk into the workspace via `extract_chunk(..., cancel_event=self._cancel_event)`, then call `client.transcribe`. Wrap the API call in the 429 retry loop:

- Catch `RateLimitError`. If attempts are exhausted (`constants.MAX_RATE_LIMIT_RETRIES`), record the failure and stop. Otherwise sleep `error.retry_after` when it is not `None`, else `RETRY_BASE_DELAY_SECONDS * 2 ** attempt`, re-checking the cancel event before sleeping and after.
- Let every other `TranscriberError` propagate to the per-chunk handler immediately — no retry for `RequestTimeoutError`, `ProviderError`, or anything else (Review Focus item 5's negative case).
- On success, record a `ChunkOutcome` and fire `on_chunk_finished`. On failure, record it and fire `on_chunk_failed`. Delete the chunk WAV in a `finally` block so temp files never accumulate across a long run.

Honor `cancel()` by setting a `threading.Event` that stops scheduling and interrupts backoff sleeps; in-flight HTTP calls are closed via `client.close()` on a best-effort basis. Fire `on_cancelled` when the event was set before completion, otherwise `on_finished`. Always remove the workspace in a `finally`.

- [ ] **Step 6: Implement `retry_failed`**

Re-submit only the indices in the previous report's `failures`, using the cached spans and workspace, and warn via `on_chunk_failed`-independent messaging that a retry may incur another charge. Return a new `TranscriptionReport` merging the prior successes with the new outcomes.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_pipeline.py -v`
Expected: PASS — no test hangs; every blocking fake is released.

- [ ] **Step 8: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: PASS

```bash
git add src/audio_transcriber/pipeline.py tests/test_pipeline.py
git commit -m "feat: orchestrate parallel chunk transcription with retry and cancellation"
```

---

### Task 9: Settings Persistence and the Key Dialog

**Files:**
- Create: `src/audio_transcriber/ui/__init__.py`
- Create: `src/audio_transcriber/ui/settings.py`
- Create: `src/audio_transcriber/ui/key_dialog.py`
- Test: `tests/test_ui_key_dialog.py`

**Interfaces:**
- Consumes: `credentials.CredentialStore` (Task 2); `constants.ZDR_WARNING` (Task 1); error classes (Task 1).
- Produces:
  - `class AppSettings` — thin wrapper over `QSettings` with `zdr_acknowledged: bool` (get/set), persisted under an app-wide org/app name.
  - `class KeyDialog(QDialog)` — `__init__(self, store: CredentialStore, parent=None)`, `.key() -> str` (empty when the user left the field blank), static `.ZDR_WARNING_TEXT = constants.ZDR_WARNING`. Contains a password-masked line edit, a non-editable read-only text area showing `ZDR_WARNING` verbatim, a **Save** button, and a **Forget key** button that calls `store.forget()` and clears the field.

- [ ] **Step 1: Write the failing tests**

Use `pytest-qt` with the `qtbot` fixture and `QApplication` on the offscreen platform.

```python
def test_zdr_warning_is_visible_verbatim(qtbot):
    dialog = KeyDialog(FakeStore())
    qtbot.addWidget(dialog)
    visible_texts = [w.toPlainText() for w in dialog.findChildren(QTextEdit)]
    assert constants.ZDR_WARNING in visible_texts
```

Plus: `test_save_persists_masked_key`, `test_blank_key_leaves_existing_key_untouched`, `test_forget_clears_the_field_and_calls_store`, and `test_store_failure_shows_message_and_does_not_store` (a store that raises `CredentialStoreUnavailable`; assert no exception escapes and an error label becomes visible).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_ui_key_dialog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.ui'`

- [ ] **Step 3: Implement `settings.py` and `KeyDialog`**

`AppSettings` wraps `QSettings("AudioTranscriber", "AudioTranscriber")` and exposes only `zdr_acknowledged`. `KeyDialog` must display the warning text and must not offer any control that implies the app can verify ZDR. Add a short line naming the OpenRouter key owner's account as the billing source. `save()` validates non-blank input, calls `store.save(...)`, and on `CredentialStoreUnavailable` shows the error in a label and keeps the dialog open. Never log or echo the entered key.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_ui_key_dialog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/audio_transcriber/ui/ tests/test_ui_key_dialog.py
git commit -m "feat: add key setup dialog with the mandatory ZDR disclaimer"
```

---

### Task 10: Main Window and Worker-Thread Wiring

**Files:**
- Create: `src/audio_transcriber/ui/main_window.py`
- Create: `src/audio_transcriber/ui/app.py`
- Create: `src/audio_transcriber/__main__.py`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: everything from Tasks 2–9.
- Produces:
  - `class PipelineWorker(QObject)`: `__init__(self, source: Path, model: str, language: str | None)`, signals `analyzing()`, `planned(int)`, `chunk_finished(int)`, `chunk_failed(int, str)`, `finished(object)`, `cancelled(object)`, plus `.cancel()` and `.retry_failed()`. Runs `TranscriptionPipeline` on a `QThread` and never touches widgets.
  - `class MainWindow(QMainWindow)`: `__init__(self, store: CredentialStore | None = None, client: OpenRouterClient | None = None, pipeline_factory=None, parent=None)`. Widgets and object names: `file_edit` (read-only path line edit), `browse_button`, `model_combo`, `language_combo`, `transcribe_button`, `cancel_button`, `retry_button`, `progress_bar`, `status_label`, `cost_label`, `transcript_edit` (`QPlainTextEdit`, read-only). Methods: `.available_models() -> list[str]` (the allowlisted models the current key may use), `.select_file() -> None`, `._start_transcription() -> None` (starts the worker; tests call this directly), `.refresh_models() -> None`.
  - `main(argv: list[str] | None = None) -> int` in `__main__.py` — handles `--self-test` by delegating to `selftest.run_self_test()`, otherwise starts `QApplication` and shows `MainWindow`.

- [ ] **Step 1: Write the failing tests**

```python
def test_zdr_disclaimer_is_visible_in_the_main_window(qtbot):
    window = MainWindow(store=FakeStore())
    qtbot.addWidget(window)
    labels = [w.text() for w in window.findChildren(QLabel)]
    assert constants.ZDR_WARNING in labels

def test_transcribe_is_blocked_until_zdr_is_acknowledged(qtbot):
    # settings.zdr_acknowledged is False; assert transcribe_button.isEnabled() is False
    # after picking a file, and that clicking it does not start a worker

def test_model_combo_offers_only_available_approved_models(qtbot):
    window = MainWindow(store=FakeStore(), client=client_returning(["openai/whisper-large-v3"]))
    qtbot.addWidget(window)
    assert window.available_models() == ["openai/whisper-large-v3"]

def test_no_approved_model_available_disables_transcription_and_explains(qtbot):
    window = MainWindow(store=FakeStore(), client=client_returning([]))
    qtbot.addWidget(window)
    assert window.transcribe_button.isEnabled() is False
    assert "no approved" in window.status_label.text().lower()

def test_progress_reaches_total_and_transcript_is_populated(qtbot, fake_pipeline_factory):
    window = MainWindow(store=FakeStore(), pipeline_factory=fake_pipeline_factory)
    qtbot.addWidget(window)
    window._start_transcription()
    qtbot.waitUntil(lambda: window.progress_bar.value() == 3, timeout=5000)
    assert window.transcript_edit.toPlainText()

def test_cancelled_run_keeps_partial_transcript_and_re_enables_retry(qtbot, blocking_pipeline_factory):
    window = MainWindow(store=FakeStore(), pipeline_factory=blocking_pipeline_factory)
    qtbot.addWidget(window)
    window._start_transcription()
    qtbot.waitUntil(lambda: window.progress_bar.value() >= 1, timeout=5000)
    window.cancel_button.click()
    qtbot.waitUntil(lambda: window.retry_button.isEnabled(), timeout=5000)
    assert window.transcript_edit.toPlainText()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_main_window.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.ui.main_window'`

- [ ] **Step 3: Implement `PipelineWorker`**

`PipelineWorker` owns a `TranscriptionPipeline` created from an injected factory (default: one `OpenRouterClient` per run). It moves itself to a `QThread` on `start()` and emits signals instead of touching widgets. Its callbacks adapter forwards pipeline callbacks to signals. `cancel()` is safe to call from the GUI thread.

- [ ] **Step 4: Implement `MainWindow`**

Layout, top to bottom: a read-only ZDR disclaimer label showing `constants.ZDR_WARNING` verbatim; a file row; an options row with `model_combo` and `language_combo` (display labels paired with ISO-639-1 item data; auto-detect stores `None`); an action row with `transcribe_button`, `cancel_button`, `retry_button`, and a reachable API-key settings control; `progress_bar`; `status_label`; `cost_label`; and `transcript_edit`.

Behavior:
- On construction, load the key from `CredentialStore`; if absent, open `KeyDialog` and cancel startup if the user does not provide one.
- Run `client.list_available_models()` asynchronously so a blocked request does not block window construction or UI events. Expose checking/error state and populate `model_combo` from that list only. If the list is empty, show `NoApprovedModelAvailable` and disable `transcribe_button`. Never insert a fallback entry.
- Key settings can replace or forget the saved key. A changed/forgotten key clears the persisted ZDR acknowledgement and stale models; a replacement key triggers asynchronous rediscovery. Never display the key.
- `transcribe_button` stays disabled until a file is chosen, a model is available, and `settings.zdr_acknowledged` is true. Acknowledgment is set from a checkbox in the disclaimer area and persisted.
- On `finished`, set `progress_bar` to the total, populate `transcript_edit` from `report.transcript()`, set `cost_label` from `report.cost_note()`, and enable Copy / Save As. If `report.is_complete` is false, `status_label` states how many chunks failed and that the text is partial.
- On `cancelled`, keep whatever text arrived, show the count of successfully completed chunks rather than setting progress to 100%, note that cancellation may still have billed in-flight requests, and enable `retry_button` when `report.failures` is non-empty.
- Copy uses `QApplication.clipboard()`. Save As opens a `QFileDialog` for `*.txt` and writes UTF-8, refusing to overwrite without confirmation. Both act on the current transcript only.

- [ ] **Step 5: Implement `app.py` and `__main__.py`**

`app.py` exposes `build_application(argv: list[str]) -> QApplication` that sets `QT_ENABLE_HIGHDPI_SCALING`, the app name, and the organization, and sets `QT_QPA_PLATFORM=offscreen` **only** when an env var `AUDIO_TRANSCRIBER_HEADLESS=1` is present (so `--self-test` works headless without changing normal behavior).

`__main__.py`'s `main(argv=None)` parses `--self-test` (delegating to `selftest.run_self_test()`), otherwise safely cleans demonstrably stale app-owned workspaces before creating the app, showing `MainWindow`, and returning `app.exec()`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_main_window.py -v`
Expected: PASS — no test leaves a modal dialog open; all use injected fakes.

- [ ] **Step 7: Smoke-run the GUI headlessly**

Run: `AUDIO_TRANSCRIBER_HEADLESS=1 timeout 10 python -c "import sys; from audio_transcriber.__main__ import main; sys.argv=['x']; print('import ok')"`
Expected: prints `import ok` and exits 0 — no window is created, no network call is made.

- [ ] **Step 8: Commit**

```bash
git add src/audio_transcriber/ui/ src/audio_transcriber/__main__.py tests/test_main_window.py
git commit -m "feat: add main window with progress, partial results, and ZDR gate"
```

---

### Task 11: Self-Test Mode

**Files:**
- Create: `src/audio_transcriber/selftest.py`
- Test: `tests/test_selftest.py`

**Interfaces:**
- Consumes: `audio.resolve_binary` (Task 4).
- Produces: `run_self_test() -> int` (0 = all checks pass, 1 = a check failed) and `class SelfTestResult(NamedTuple)`: `checks: list[tuple[str, bool, str]]`, `.ok: bool` (property).

- [ ] **Step 1: Write the failing tests**

```python
def test_self_test_reports_qt_and_ffmpeg_checks():
    result = run_self_test(probe_fn=fake_probe_ok)
    names = [name for name, _, _ in result.checks]
    assert "qt-initialised" in names
    assert "ffmpeg" in names and "ffprobe" in names
    assert result.ok is True

def test_self_test_fails_when_a_binary_is_missing():
    assert run_self_test(binary_probe=fake_probe_missing_ffmpeg).ok is False

def test_self_test_makes_no_network_call_and_reads_no_credential(monkeypatch):
    monkeypatch.setattr("socket.socket", boom)
    monkeypatch.setattr("keyring.get_password", boom)
    assert run_self_test(probe_fn=fake_probe_ok).ok is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_selftest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'audio_transcriber.selftest'`

- [ ] **Step 3: Implement `selftest.py`**

`run_self_test(probe_fn=None, binary_probe=None)` runs, in order, and records `(name, ok, detail)` triples: `python-version` (3.11+); `qt-initialised` (set `QT_QPA_PLATFORM=offscreen`, import `PySide6.QtWidgets`, construct and immediately discard a `QApplication`); `ffmpeg` and `ffprobe` (`resolve_binary` then a `-version` subprocess with a 20-second timeout, checking return code 0). Print a one-line-per-check summary to stdout, **write the same lines to `self-test.log` next to the executable** (the packaged app is windowed, so stdout is unreliable), and return `0 if all checks passed else 1`. Never construct `MainWindow`, never touch `CredentialStore`, never open a socket.

- [ ] **Step 4: Run the tests and then the real self-test**

Run: `python -m pytest tests/test_selftest.py -v && python -m audio_transcriber --self-test; echo "exit=$?"`
Expected: tests PASS, then four check lines and `exit=0` on this machine (ffmpeg and ffprobe are installed).

- [ ] **Step 5: Commit**

```bash
git add src/audio_transcriber/selftest.py tests/test_selftest.py
git commit -m "feat: add headless self-test for Qt and bundled FFmpeg"
```

---

### Task 12: Packaging — PyInstaller Onedir Build and Release ZIP

**Files:**
- Create: `packaging/AudioTranscriber.spec`
- Create: `packaging/fetch_ffmpeg.py`
- Create: `packaging/build_release.py`
- Test: `tests/test_build_release.py`

**Interfaces:**
- Consumes: the package entry point (`audio_transcriber.__main__:main`) and `selftest.run_self_test`.
- Produces: `build_release.build(version: str, *, output_dir: Path, repo_root: Path) -> Path` returning the path of the created `AudioTranscriber-v<version>-win-x64.zip`. `build_release.zip_contents(zip_path: Path) -> list[str]` for tests. The pinned fetcher returns the verified FFmpeg source archive and signature; the UCRT64 builder stages both tools and all shared DLLs with source/license provenance.

- [ ] **Step 1: Write the failing tests**

```python
def test_zip_contains_expected_layout(tmp_path):
    zip_path = build_release.build("9.9.9", output_dir=tmp_path, repo_root=REPO_ROOT, runner=fake_pyinstaller_runner)
    names = build_release.zip_contents(zip_path)
    assert any(n.endswith("AudioTranscriber.exe") for n in names)
    assert any(n.endswith("ffmpeg.exe") for n in names)
    assert any(n.endswith("ffprobe.exe") for n in names)
    assert any("LICENSES" in n for n in names)

def test_zip_root_folder_is_named_for_the_app(tmp_path):
    ... assert all(n.startswith("AudioTranscriber/") for n in names)

def test_zip_contains_no_audio_or_secret_files(tmp_path):
    ... assert not [n for n in names if n.lower().endswith((".wav", ".m4a", ".mp3", ".env"))]

def test_spec_file_is_onedir_not_onefile():
    spec = (REPO_ROOT / "packaging/AudioTranscriber.spec").read_text()
    assert "COLLECT" in spec            # onedir collection
    assert "onefile" not in spec.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_build_release.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'build_release'`

Add `REPO_ROOT = Path(__file__).resolve().parents[1]` and `sys.path.insert(0, str(REPO_ROOT / "packaging"))` at the top of the test module, and a `fake_pyinstaller_runner` that creates a minimal `dist/AudioTranscriber/` tree containing placeholder `AudioTranscriber.exe`, `ffmpeg.exe`, `ffprobe.exe`, and a `LICENSES/` directory instead of invoking PyInstaller.

- [ ] **Step 3: Write `packaging/AudioTranscriber.spec`**

A PyInstaller spec using `Analysis` + `COLLECT` (never `EXE` alone / `onefile`). It sets `name="AudioTranscriber"` and `console=False`, and excludes unneeded Qt modules (`PySide6.QtQml`, `PySide6.QtQuick`, `PySide6.Qt3DCore`, `PySide6.QtWebEngineCore`) and test packages. It adds `binaries` entries for `ffmpeg.exe`, `ffprobe.exe`, and each FFmpeg `*.dll` in `packaging/bin/`, placing them at the onedir root; the `LICENSES` directory remains a data entry. Missing optional FFmpeg assets are not fabricated.

Because `console=False` builds a windowed executable on Windows, `stdout` is not reliable in the packaged app. `selftest.run_self_test()` must therefore **also** write its per-check lines to a file next to the executable (`self-test.log`, overwritten each run) in addition to printing them, and CI verifies the log and the exit code rather than console output.

- [ ] **Step 4: Write `packaging/fetch_ffmpeg.py`**

`fetch(dest_dir)` downloads only official FFmpeg 9.0.2 source and its detached signature, validates the pinned SHA-256, and rejects altered cache entries. `packaging/build_ffmpeg.sh` verifies the signature against the pinned FFmpeg release-key fingerprint, builds shared libraries under MSYS2 UCRT64 with GPL/version-3/nonfree/autodetect/network features disabled, and stages the executables, every runtime DLL, the source/signature/key, LGPL license, toolchain notices, source offer, and generated hashes. `packaging/smoke_test_ffmpeg.py` exercises local WAV/M4A/OGG/FLAC probe/decode, MP3 decoder registration, silence detection, and canonical 16 kHz mono `pcm_s16le` output using only generated temporary WAV media.

- [ ] **Step 5: Write `packaging/build_release.py`**

`build(version, output_dir, repo_root, runner=None)` rejects a version that differs from `audio_transcriber.__version__`, invokes PyInstaller with the spec, requires substantive license material for active direct/transitive package and PyInstaller bootloader distributions, and requires the pinned FFmpeg source/signature/license/build material and matching source/runtime hashes. Missing or altered provenance prevents ZIP creation. The README documents both the manual Actions test artifact and the latest GitHub Release without duplicating a version literal.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python -m pytest tests/test_build_release.py -v`
Expected: PASS

- [ ] **Step 7: Verify the spec parses without building**

Run: `python -c "import ast,pathlib; ast.parse(pathlib.Path('packaging/AudioTranscriber.spec').read_text()); print('spec parses')"`
Expected: prints `spec parses`.

- [ ] **Step 8: Commit**

```bash
git add packaging/ tests/test_build_release.py
git commit -m "build: package onedir Windows app with bundled FFmpeg"
```

---

### Task 13: CI Workflow, README, and License Notices

**Files:**
- Create: `.github/workflows/release.yml`
- Create: `README.md`
- Create: `LICENSES/README.md`
- Modify: `.gitignore` (add `packaging/bin/`, already present — verify, do not duplicate)

**Interfaces:**
- Consumes: `python -m pytest`, `packaging/fetch_ffmpeg.py`, `packaging/build_release.py`, `python -m audio_transcriber --self-test`.
- Produces: a Windows workflow that tests, builds pinned FFmpeg from source, smoke-tests local features, packages and self-tests the app, uploads an Actions artifact for the candidate-branch push or manual dispatch, and publishes the ZIP only for version-tag pushes in a separate write-permission job.

- [ ] **Step 1: Write `.github/workflows/release.yml`**

Triggers: `push` and `workflow_dispatch`. The Windows build job is guarded to run for version tags, manual dispatches, and pushes to `feat/pinned-lgpl-ffmpeg`; other branch pushes skip the job. It runs on `windows-2022`, sets up MSYS2 UCRT64 with MinGW GCC, NASM, and GnuPG; runs the Python suite; source-builds and signature-verifies pinned FFmpeg 9.0.2; runs the synthetic-media FFmpeg smoke test; packages the ZIP; and runs `AudioTranscriber.exe --self-test` (must exit 0, and `self-test.log` must contain the four check lines). Candidate-branch pushes and manual dispatch upload `AudioTranscriber-windows-test` and do not create a GitHub Release. The build job has read-only repository permissions; a separate tag-only publish job downloads the release artifact and has `contents: write`.

The workflow must define **no** `secrets` or `env` containing an OpenRouter key, and no step may upload `.wav`/`.m4a` files. Add a comment stating both facts explicitly.

- [ ] **Step 2: Verify no secrets appear in the workflow**

Run: `grep -n -i -E "sk-or|OPENROUTER_API_KEY|secrets\." .github/workflows/release.yml; echo "exit=$?"`
Expected: prints only `exit=1` (no matches).

- [ ] **Step 3: Write `README.md`**

Sections cover app behavior, Privacy and ZDR, version-independent latest-Release and manual Actions test-artifact download instructions, the pinned FFmpeg source/build validation status, first run, key replacement/forget settings, language code behavior, costs, troubleshooting, and privacy details.

- [ ] **Step 4: Write `LICENSES/README.md`**

Index the pinned source-built FFmpeg/FFprobe configuration and pending Windows validation; PySide6, Qt, and Python; and the active direct/transitive package inventory generated from the Windows packaging environment (including PyInstaller and its bootloader). Copy substantive full texts/notices and exact FFmpeg source/build provenance into the ZIP and fail packaging if any required license, signature, source, recipe, or hash material is missing. Do not claim legal compliance without review of the exact built output and applicable notices.

- [ ] **Step 5: Verify the README states the ZDR warning verbatim**

Run: `python -c "from pathlib import Path; from audio_transcriber.constants import ZDR_WARNING; t=Path('README.md').read_text(); print('verbatim present' if ZDR_WARNING in t else 'MISSING')"`
Expected: prints `verbatim present`.

- [ ] **Step 6: Run the full suite and commit**

Run: `python -m pytest tests/ -q`
Expected: PASS

```bash
git add .github/workflows/release.yml README.md LICENSES/ .gitignore
git commit -m "docs: add CI release workflow, README, and license notices"
```

---

### Task 14: End-to-End Verification Against Real Media

**Files:**
- Modify: none
- Test: `tests/test_end_to_end.py` (opt-in, skipped without an explicit env var)

**Interfaces:**
- Consumes: `audio.probe`, `detect_quiet_midpoints`, `extract_chunk`, `chunking.plan_chunks`, `openrouter_client.OpenRouterClient` with a `MockTransport`, `pipeline.TranscriptionPipeline`.
- Produces: a test that exercises the whole local pipeline on a real recording with a mocked API, uploading nothing and spending nothing.

- [ ] **Step 1: Write the opt-in end-to-end test**

Guard it with `@pytest.mark.skipif(not os.environ.get("AUDIO_TRANSCRIBER_SAMPLE"), reason="set AUDIO_TRANSCRIBER_SAMPLE to a local media path")`, where the env var is a **path** read at test time — never committed. The test probes the file, detects quiet points, plans chunks, extracts the first three chunks, asserts each is 16 kHz mono `pcm_s16le` via `ffprobe`, feeds them to `OpenRouterClient` behind an `httpx.MockTransport` that returns a canned `{"text": ..., "usage": {...}}`, and asserts the assembled transcript and summed cost. It must never reach the network.

- [ ] **Step 2: Run it against the provided sample**

Run: `AUDIO_TRANSCRIBER_SAMPLE="/home/parth/Desktop/Code/audio-transcriber/Voice 260811_090358.m4a" python -m pytest tests/test_end_to_end.py -v`
Expected: PASS — probing, quiet detection, chunk planning, and extraction succeed on a real 60 MB AAC recording, with no billed request.

- [ ] **Step 3: Report the real chunk count for the 104-minute sample**

Run: `python -c "from audio_transcriber.chunking import plan_chunks; s=plan_chunks(6247.155729); print(f'{len(s)} chunks, total audio {sum(x.duration for x in s):.1f}s vs source 6247.2s')"`
Expected: roughly 210 chunks and a total a few percent above the source duration, confirming the overlap overhead is small. Quote this number to the user rather than assuming it.

- [ ] **Step 4: Confirm no personal media or transcript was committed**

Run: `git status --porcelain && git log --stat --oneline -1 && ls *.wav *.m4a 2>/dev/null; echo "clean=$?"`
Expected: empty `git status --porcelain`, the last commit touching only source/test/doc files, and no audio file in the repo root.

- [ ] **Step 5: Commit**

```bash
git add tests/test_end_to_end.py
git commit -m "test: add opt-in end-to-end check against local media"
```
