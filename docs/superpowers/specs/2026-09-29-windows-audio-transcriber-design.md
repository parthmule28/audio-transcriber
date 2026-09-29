# Windows Audio Transcriber — Design

**Date:** 2026-09-29
**Status:** For user review

## Intent

Build a simple Windows desktop app that lets a non-technical user choose an audio file, transcribe it, and copy or save the result without using a terminal. The app will call OpenRouter’s speech-to-text API, use the account owner’s existing OpenRouter key and ZDR policy, and be downloadable from this public GitHub repository as a Windows release.

The repository was empty when this design was prepared. Audio files currently present in the original workspace are personal inputs and are not part of this repository or release.

## Goals and boundaries

- A familiar GUI with file selection, progress, a transcript preview, copy, and save-as-`.txt`.
- Support OpenRouter STT models `openai/whisper-large-v3-turbo` (default) and `openai/whisper-large-v3` (accuracy-oriented alternative). Do not use `openai/whisper-1` or `openai/text-embedding-3-large` for transcription.
- Store the API key in Windows Credential Manager for the current Windows user. The key must not be embedded in source, the executable, CI, logs, or GitHub.
- Process audio locally with bundled FFmpeg, send only the audio chunks needed for transcription, and remove temporary chunks afterward.
- Publish a portable Windows x64 executable in a GitHub Release.

Out of scope for the first release: embeddings/search, speaker diarization, live recording, subtitle formats, local/offline transcription, and account/key provisioning.

## User flow

1. On first launch, the app asks for an OpenRouter API key and explains that usage is billed to the account associated with that key. It stores the key in Windows Credential Manager. The settings UI can replace or forget the key.
2. After key setup, the app discovers transcription models through the authenticated `/api/v1/models/user?output_modalities=transcription` endpoint, which filters availability using that account’s provider and privacy preferences. It offers only the two approved Whisper model IDs when available. Turbo is selected by default.
3. The user selects a supported audio/video file, optionally selects a language (default: automatic detection), and clicks **Transcribe**.
4. The app shows chunk progress and the assembled transcript. The user copies it or chooses a destination for a plain-text file. Returned OpenRouter usage and cost are shown when present; if cost is not returned, the app says it is unavailable rather than estimating it as fact.

## Architecture and audio pipeline

Use a Python desktop application with PySide6. Keep the GUI, audio preparation/chunking, OpenRouter client, and credential handling in separate modules so API and audio behavior can be tested without rendering the UI.

FFprobe inspects the selected file before processing. FFmpeg extracts the audio stream, resamples to 16 kHz mono for Whisper-style speech recognition, and encodes temporary chunks as FLAC where conversion is needed. Already compatible inputs should avoid unnecessary transcoding where practical. Video content and non-audio streams are ignored. The original input is never modified.

For long recordings, target approximately 30-second chunks, placing boundaries near a local quiet point when one is close to the target. Retain a short overlap (about one second) to reduce cut-off words, and remove repeated overlap text when joining results. Process chunks concurrently with a conservative fixed limit of three requests. Short recordings need not be split. The OpenRouter endpoint accepts base64 JSON audio; each chunk is sent independently to `POST /api/v1/audio/transcriptions` with the selected model and detected/selected format. Leave language automatic unless the user chooses a language, and use deterministic temperature settings where supported.

Preprocessing should preserve speech rather than aggressively alter it: do not strip silence, denoise, or apply dynamic compression by default. Resampling/downmixing and a compatible, compact audio encoding reduce format and transfer friction, but do not reduce duration-based model billing. Chunk overlap can slightly increase billed audio. Turbo is the default for its speed/cost positioning; Large V3 remains available when the user prefers the accuracy-oriented model. Actual returned usage is the source of truth for displayed cost.

## Privacy and ZDR

The API key is entered by the user and stored using the Windows Credential Manager backend; the app must fail closed if secure storage is unavailable rather than falling back to a plaintext file. Never log the key, audio, or transcript. No telemetry or remote transcript storage is included. Temporary audio chunks are held in the current user’s temporary directory and deleted after completion/cancellation; stale app-owned temporary files are cleaned up on startup. The user explicitly chooses where to save a transcript.

ZDR is enforced by the OpenRouter account’s privacy settings for the account associated with the supplied key. The token owner must have ZDR enabled for applicable provider/model groups. The transcription API schema documents provider passthrough options but does not document the `provider.zdr` preference, so the app must not rely on that undocumented STT request field. Use the authenticated, privacy-filtered model list for discovery and do not silently fall back to another model. If an approved model is unavailable under the account’s configured preferences, explain the issue and stop. The app cannot independently prove the account’s ZDR setting; setup instructions must say that account-level ZDR is a prerequisite.

Because the key will be used on another person’s computer, the preferred operational practice is a separate OpenRouter key with an appropriate spend limit, rather than a primary/management credential. Regardless, the executable and public repository contain no key.

## Errors, retries, and cancellation

- Translate authentication, insufficient-credit, unsupported-model, invalid-audio, rate-limit, and provider errors into readable messages.
- Retry rate-limit responses with bounded backoff, honoring `Retry-After` when present. Do not automatically retry timeouts or ambiguous provider/server errors: the upstream request might already have been processed and billed.
- Keep successful chunk results in memory and in the progress view. Let the user explicitly retry failed chunks with a warning that a retry may incur another charge.
- Cancellation stops scheduling new chunks and cancels in-flight requests on a best-effort basis. Tell the user that a request already received by a provider may still complete or be billed.
- Preserve input order when joining results; make partial output available with a clear incomplete status if one or more chunks fail.

## Packaging and release

Use PyInstaller to package a portable Windows x64 app and bundle the required FFmpeg/FFprobe binaries with their license notices. A GitHub Actions workflow builds on a Windows runner and attaches a ZIP containing the executable and runtime assets to a versioned GitHub Release. CI has no OpenRouter secret. The first release is unsigned; Windows SmartScreen may display an unknown-publisher warning.

The README will cover downloading/running the release, entering a key, enabling ZDR on the key owner’s account, selecting audio, saving transcripts, and basic troubleshooting. It will state that audio is sent to OpenRouter for transcription and explain that parallel chunking improves latency, not unit cost.

## Verification and acceptance

- Unit tests cover model filtering, safe credential handling, FFmpeg probing/conversion, chunk boundaries/overlap, ordered transcript assembly, cleanup, cancellation, and API error mapping.
- Mocked HTTP tests verify the OpenRouter JSON/base64 request and usage handling without a paid API call or audio upload.
- CI runs tests and produces the Windows package. A packaging smoke test verifies the executable starts and includes FFmpeg/FFprobe.
- No API key, sample recording, transcript, or generated temporary audio is committed or uploaded by CI.
- Acceptance: a user can download and launch the Windows release, enter a key once, select an `.m4a` or other supported file, see progress, obtain a transcript, and save/copy it. Only the two approved Whisper models are offered, and an unavailable model does not trigger a fallback.

## Research references

- [OpenRouter Speech-to-Text](https://openrouter.ai/docs/guides/overview/multimodal/stt) — transcription endpoint, accepted payloads, supported formats, usage, and timeout/chunking guidance.
- [OpenRouter Zero Data Retention](https://openrouter.ai/docs/guides/features/zdr) — account and provider endpoint ZDR policies and enforcement.
- [OpenRouter user-filtered models API](https://openrouter.ai/docs/api/api-reference/models/list-models-filtered-by-user-provider-preferences-privacy-settings-and-guardrails) — model discovery filtered by the key owner’s privacy settings.
- [OpenRouter model endpoints API](https://openrouter.ai/api/v1/models/openai/whisper-large-v3/endpoints) and [ZDR endpoint list](https://openrouter.ai/api/v1/endpoints/zdr) — live route availability checked on 2026-09-29. At that check, both Large V3 and Turbo appeared in the ZDR endpoint list; the available providers can change.
- [Groq Speech-to-Text guidance](https://console.groq.com/docs/speech-to-text) — Whisper-oriented 16 kHz mono preprocessing, lossless FLAC size reduction, and overlapping chunking. This is provider guidance, not a guarantee that every OpenRouter route behaves identically.
- [Python keyring Windows backend](https://github.com/jaraco/keyring/blob/main/keyring/backends/Windows.py) — Windows Credential Manager integration.
