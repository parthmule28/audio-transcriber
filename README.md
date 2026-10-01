# Windows Audio Transcriber

## What this app does

Windows desktop app for turning a local audio recording into a transcript. It prepares audio locally with FFmpeg, then sends audio chunks to OpenRouter for speech recognition. The app offers the approved Whisper Large V3 Turbo and Whisper Large V3 models, shows progress and the transcript, and lets you copy or save the result as a text file. Transcription requires an internet connection and an OpenRouter inference API key.

## Privacy and ZDR

> **“ZDR must be enforced on this API key/account. The application cannot verify or enforce this for transcription.”**

Before sharing a key, the account owner should create a **dedicated inference API key** for this app and attach a **key-bound guardrail** that enforces Zero Data Retention (ZDR) for the applicable model group and sets a spend limit. The guardrail must be assigned to that key; an unassigned guardrail does nothing. Account privacy settings still apply.

The app cannot inspect a key's guardrail assignment or verify ZDR. It does not enforce ZDR on transcription requests, and a model appearing as available is not proof that ZDR is enabled. Audio is sent to OpenRouter for transcription, so review the account's provider and privacy settings before use. Use an inference key—not a Management API key. The app stores the key in Windows Credential Manager.

## Download and run

### Windows test build

Pushing the `feat/pinned-lgpl-ffmpeg` branch starts the Windows candidate build and uploads an `AudioTranscriber-windows-test` artifact on success. Download it from that branch's Actions run. This push-based path allows Windows validation before the workflow is present on the default branch. Once the workflow is on the default branch, you can also open **Actions → Windows release → Run workflow**, select the feature branch, and enter version `0.1.0`. **Neither path creates a GitHub Release.** Only a version-tag push can publish one.

The candidate build compiles FFmpeg 9.0.2 from the pinned official source archive (`https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz`, SHA-256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`) and verifies its detached signature against release-key fingerprint `FCF986EA15E6E293A5644F10B4322F04D67658D8`. Its Windows ZIP contains the source, signature, key, LGPL license text, build recipe, toolchain notices, and generated provenance. The build disables GPL, version-3-only, nonfree, autodetection, and network features. Workflow validation is still required before treating a candidate artifact as tested; see [`LICENSES/FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md`](LICENSES/FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md).

When a release is available, download the Windows x64 ZIP attached to the latest GitHub Release.
1. Unzip the archive. Open the extracted `AudioTranscriber` folder and run `AudioTranscriber.exe`; keep the supporting files in that folder.
2. The release is unsigned. Windows SmartScreen may show an unknown-publisher warning. Confirm that you downloaded the archive from the project's Releases page before choosing **More info** and **Run anyway**.

## First run

Enter the dedicated OpenRouter inference key provided by the account owner. The key owner's account is billed for requests made with that key. Review and acknowledge the ZDR warning before transcribing. The key is saved in Windows Credential Manager; the app does not fall back to storing it in a plain-text file. Use **API key settings** to replace or forget the saved key; changing or forgetting it clears the previous ZDR acknowledgement and requires rediscovery for the new key.

## Selecting audio and transcribing

Choose a supported audio file, select an available Whisper model and (optionally) a language, then start transcription. Language choices are sent as ISO-639-1 codes; automatic detection is the default. FFmpeg prepares the audio and the app processes it in overlapping chunks while showing progress. The default is Whisper Large V3 Turbo; Whisper Large V3 is the alternative. If neither approved model is available to the key, the app stops rather than silently switching to another model. A file with no readable audio track cannot be transcribed.

## Saving and copying the transcript

When text is available, use **Copy** to put it on the clipboard or **Save As** to save a plain-text file where you choose. Saving is explicit; the app does not automatically write a transcript beside the source recording.

## Cost

Chunking improves latency, not unit cost. Overlap means a small amount of audio may be sent more than once and can add slightly to billed audio. Any displayed total is only the usage cost OpenRouter reports; the app does not estimate missing costs. If OpenRouter does not report a cost for every chunk, the total is shown as unavailable.

## Troubleshooting

- **401 — invalid credentials:** Check that the entered inference key is active and copied correctly. Replace it in the app if needed.
- **402 — insufficient credits:** The key owner's account may need credits or billing attention.
- **403 — forbidden:** Check the key's model access and account restrictions. Confirm the intended guardrail is assigned; do not remove privacy protections as a workaround.
- **429 — rate limited:** The app retries rate-limit responses a bounded number of times. Wait and try again later if the limit persists.
- **SmartScreen warning:** The release is unsigned, so an unknown-publisher warning is expected. Proceed only if the archive came from the project's Releases page and you trust it.
- **“No audio stream”:** The selected file may have no audio track or may be unreadable. Choose a file with a readable audio track.
- **Incomplete transcript:** Review which chunks failed. You can explicitly retry failed chunks; **a retry may be billed again** if the provider already processed the original request.
- **FFmpeg or FFprobe missing:** Run the executable from the extracted `AudioTranscriber` folder and keep the accompanying files together.

## Privacy details

The app includes no telemetry and has no remote transcript storage or cloud library. Audio is sent to OpenRouter to perform transcription; provider handling and retention depend on the account's privacy settings and assigned guardrail. Temporary WAV chunks are cleaned up when processing completes or is cancelled, and stale app-owned temporary workspaces are cleaned on startup. The original file is never modified.
