# Windows Audio Transcriber — Design

**Date:** 2026-09-29
**Status:** For user review

## Intent

Build a simple Windows desktop app that lets a non-technical user choose an audio file, transcribe it, and copy or save the result without using a terminal. The app will call OpenRouter’s speech-to-text API using a dedicated, account-owned inference key with an assigned ZDR-and-budget guardrail, and be downloadable from this public GitHub repository as a Windows release.

The repository was empty when this design was prepared. Audio files currently present in the original workspace are personal inputs and are not part of this repository or release.

## Goals and boundaries

- A familiar GUI with file selection, progress, a transcript preview, copy, and save-as-`.txt`.
- Support OpenRouter STT models `openai/whisper-large-v3-turbo` (default) and `openai/whisper-large-v3` (accuracy-oriented alternative). Do not use `openai/whisper-1` or `openai/text-embedding-3-large` for transcription.
- Store the API key in Windows Credential Manager for the current Windows user. The key must not be embedded in source, the executable, CI, logs, or GitHub.
- Process audio locally with bundled FFmpeg, send only the audio chunks needed for transcription, and remove temporary chunks afterward.
- Publish a portable Windows x64 application folder, distributed as a ZIP in a GitHub Release.

Out of scope for the first release: embeddings/search, speaker diarization, live recording, subtitle formats, local/offline transcription, and account/key provisioning.

## User flow

1. Before sharing the app, the account owner creates a dedicated OpenRouter inference API key, attaches a key-bound guardrail that enforces ZDR for the applicable model group(s) and sets a spend limit, and gives that key to the user. On first launch, the app explains that usage is billed to the key owner’s account and stores the key in Windows Credential Manager. The settings UI can replace or forget the key.
2. The app displays this warning during key setup and before transcription: **“ZDR must be enforced on this API key/account. The application cannot verify or enforce this for transcription.”** The user must acknowledge the warning before the first transcription.
3. After key setup, the app discovers available transcription models through the authenticated `/api/v1/models/user?output_modalities=transcription` endpoint, which filters availability using the key owner’s provider preferences, privacy settings, and guardrails. It offers only the two approved Whisper model IDs when available. Turbo is selected by default. Model availability is not presented as proof that ZDR is enabled.
4. The user selects a supported audio/video file, optionally selects a language (default: automatic detection), and clicks **Transcribe**.
5. The app shows chunk progress and the assembled transcript. The user copies it or chooses a destination for a plain-text file. Returned OpenRouter usage and cost are shown when present; if cost is not returned, the app says it is unavailable rather than estimating it as fact.

## Architecture and audio pipeline

Use a Python desktop application with PySide6. Keep the GUI, audio preparation/chunking, OpenRouter client, and credential handling in separate modules so API and audio behavior can be tested without rendering the UI.

FFprobe inspects the selected file before processing. FFmpeg always decodes the selected audio stream to canonical 16 kHz, mono, signed 16-bit PCM WAV, the safest common format for provider compatibility. Video content and non-audio streams are ignored. The original input is never modified. Every API chunk uses the same WAV encoding; there is no pass-through or source-format optimization in v1.

Chunking is fixed in code and is not exposed in the UI:

```python
TARGET_CHUNK_SECONDS = 30
OVERLAP_SECONDS = 1
MAX_CONCURRENT_REQUESTS = 3
```

Place boundaries near a local quiet point when one is close to the target; otherwise use the target boundary. Short recordings need not be split. A 30-second canonical WAV is approximately 960 KB before base64 encoding and 1.28 MB afterward. Send each chunk independently as base64 JSON to `POST /api/v1/audio/transcriptions` with the selected model and `wav` format. Leave language automatic unless the user chooses a language, and use deterministic temperature settings where supported.

When assembling adjacent chunk transcripts, compare only a small suffix of chunk N against a small prefix of chunk N+1. Remove a repeated boundary only when there is a clear normalized token match; if uncertain, keep both. Never globally remove repeated phrases elsewhere in the transcript.

Preprocessing should preserve speech rather than aggressively alter it: do not strip silence, denoise, or apply dynamic compression. Canonical WAV is chosen for consistent provider compatibility and predictable audio bytes, not as a billing optimization. Resampling/downmixing and chunking do not reduce duration-based model billing; overlap can slightly increase billed audio. Turbo is the default for its speed/cost positioning; Large V3 remains available when the user prefers the accuracy-oriented model. Actual returned usage is the source of truth for displayed cost.

## Privacy and ZDR

The dedicated inference API key is entered by the user and stored using the Windows Credential Manager backend; the app must fail closed if secure storage is unavailable rather than falling back to a plaintext file. Do not accept or require a Management API key. Never log the key, audio, or transcript. No telemetry or remote transcript storage is included. Temporary WAV chunks are held in the current user’s temporary directory and deleted after completion/cancellation; stale app-owned temporary files are cleaned up on startup. The user explicitly chooses where to save a transcript.

For use on another person’s computer, the account owner must use a dedicated inference API key with a key-bound OpenRouter guardrail that both enforces ZDR and sets a spend limit. The guardrail must be assigned to that key; an unassigned guardrail has no effect. Applicable account privacy settings still apply. The OpenRouter STT endpoint does not support per-request data-policy enforcement; its `provider` field is for provider-specific options. Never send `provider.zdr` or imply that the app can enforce ZDR on an STT request.

The authenticated `/models/user?output_modalities=transcription` call is used only to discover model availability after key preferences and guardrails have been applied. A model appearing in that result is not proof that ZDR is enabled. The app cannot inspect the key’s guardrail assignment or independently verify ZDR enforcement. Display the warning verbatim in the UI and README, require acknowledgement before first transcription, and do not imply that model discovery is a privacy check. If an approved model is unavailable, explain the issue and stop; never silently fall back to another model.

The app does not create keys, guardrails, or account settings. The executable, repository, and CI contain no API key or Management API key.

## Errors, retries, and cancellation

- Translate authentication, insufficient-credit, unsupported-model, invalid-audio, rate-limit, and provider errors into readable messages.
- Retry rate-limit responses with bounded backoff, honoring `Retry-After` when present. Do not automatically retry timeouts or ambiguous provider/server errors: the upstream request might already have been processed and billed.
- Keep successful chunk results in memory and in the progress view. Let the user explicitly retry failed chunks with a warning that a retry may incur another charge.
- Cancellation stops scheduling new chunks and cancels in-flight requests on a best-effort basis. Tell the user that a request already received by a provider may still complete or be billed.
- Preserve input order when joining results; make partial output available with a clear incomplete status if one or more chunks fail.

## Packaging and release

Use PyInstaller `--onedir` to package a portable Windows x64 app folder. The release ZIP contains:

```text
AudioTranscriber/
  AudioTranscriber.exe
  ffmpeg.exe
  ffprobe.exe
  Qt/runtime files
  LICENSES/
```

Publish `AudioTranscriber-v0.1.0-win-x64.zip` (version updated for subsequent releases) from a GitHub Actions build on a Windows runner. Include an internal `AudioTranscriber.exe --self-test` mode that imports/initializes Qt using its offscreen platform, checks the bundled FFmpeg and FFprobe binaries, and exits with a meaningful status code without showing the main window, accessing credentials, or making network requests. CI runs this self-test after packaging. Include FFmpeg and dependency license notices. CI has no OpenRouter secret. The first release is unsigned; Windows SmartScreen may display an unknown-publisher warning.

The README will cover downloading/unzipping/running the release, creating a dedicated inference key, attaching a key-bound ZDR-and-budget guardrail, entering the key, selecting audio, saving transcripts, and basic troubleshooting. It will state prominently that ZDR must be enforced on the key/account and that the application cannot verify or enforce this for transcription. It will state that audio is sent to OpenRouter and explain that parallel chunking improves latency, not unit cost.

## Verification and acceptance

- Unit tests cover model allowlisting/availability, safe credential handling, FFmpeg probing and canonical WAV conversion, fixed chunk constants and overlap, conservative adjacent-boundary deduplication, ordered transcript assembly, cleanup, cancellation, and API error mapping.
- Mocked HTTP tests verify the OpenRouter JSON/base64 request and usage handling without a paid API call or audio upload.
- CI runs tests and produces the Windows onedir ZIP. The packaged `--self-test` verifies Qt initialization and FFmpeg/FFprobe availability without opening the main window.
- UI tests or focused checks verify the ZDR disclaimer is visible before transcription and is not contradicted by model discovery.
- No API key, sample recording, transcript, or generated temporary audio is committed or uploaded by CI.
- Acceptance: a user can download/unzip the Windows release, launch `AudioTranscriber.exe`, enter a dedicated key once, select an `.m4a` or other supported file, see progress, obtain a transcript, and save/copy it. Only the two approved Whisper models are offered, an unavailable model does not trigger a fallback, and the app does not claim to verify ZDR.

## Research references

- [OpenRouter Speech-to-Text](https://openrouter.ai/docs/guides/overview/multimodal/stt) — transcription endpoint, accepted payloads, supported formats, usage, and timeout/chunking guidance.
- [OpenRouter Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr) — account and provider endpoint ZDR policies and enforcement.
- [OpenRouter user-filtered models API](https://openrouter.ai/docs/api/api-reference/models/list-models-filtered-by-user-provider-preferences-privacy-settings-and-guardrails) — model discovery filtered by the key owner’s privacy settings.
- [OpenRouter Guardrails](https://openrouter.ai/docs/guides/features/guardrails) — key-specific guardrail assignments, ZDR controls, and per-guardrail spending limits. A guardrail must be assigned to enforce its settings.
- [OpenRouter STT request schema](https://openrouter.ai/docs/api/api-reference/stt/create-transcription) — STT provider options; per-request data-policy enforcement is not supported for this endpoint.
- [OpenRouter model endpoints API](https://openrouter.ai/api/v1/models/openai/whisper-large-v3/endpoints) and [ZDR endpoint list](https://openrouter.ai/api/v1/endpoints/zdr) — live route availability checked on 2026-09-29. At that check, both Large V3 and Turbo appeared in the ZDR endpoint list; the available providers can change.
- [Groq Speech-to-Text guidance](https://console.groq.com/docs/speech-to-text) — Whisper-oriented 16 kHz mono preprocessing, lossless FLAC size reduction, and overlapping chunking. This is provider guidance, not a guarantee that every OpenRouter route behaves identically.
- [Python keyring Windows backend](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py) — Windows Credential Manager integration.
