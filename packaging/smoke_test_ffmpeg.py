"""Exercise the bundled FFmpeg build with synthetic, local-only media."""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import subprocess
import sys
import tempfile
import wave
from collections.abc import Callable, Sequence
from pathlib import Path


SAMPLE_RATE = 16_000


def _write_synthetic_wav(path: Path) -> None:
    """Generate a short tone/silence/tone WAV without external media or codecs."""
    tone_samples = SAMPLE_RATE * 3 // 4
    silence_samples = SAMPLE_RATE * 2 // 5
    frames = []
    for index in range(tone_samples):
        value = round(9000 * math.sin(2 * math.pi * 440 * index / SAMPLE_RATE))
        frames.append(value)
    frames.extend([0] * silence_samples)
    for index in range(tone_samples):
        value = round(9000 * math.sin(2 * math.pi * 660 * index / SAMPLE_RATE))
        frames.append(value)

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(struct.pack(f"<{len(frames)}h", *frames))


def _run(
    argv: Sequence[str | Path], *, runner: Callable | None = None
) -> subprocess.CompletedProcess:
    if runner is None:
        runner = subprocess.run
    command = [str(part) for part in argv]
    result = runner(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        details = (result.stderr or result.stdout or "no diagnostic output").strip()
        raise RuntimeError(
            f"{Path(command[0]).name} failed with exit code {result.returncode}: {details}"
        )
    return result


def _probe_audio(
    ffprobe: Path, media: Path, *, runner: Callable | None = None
) -> dict[str, object]:
    result = _run(
        (
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name,sample_rate,channels",
            "-of",
            "json",
            media,
        ),
        runner=runner,
    )
    try:
        streams = json.loads(result.stdout)["streams"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError(f"FFprobe returned invalid stream information for {media.name}") from exc
    if len(streams) != 1:
        raise RuntimeError(f"Expected one audio stream in {media.name}, found {len(streams)}")
    return streams[0]


def run_smoke_test(
    ffmpeg: Path, ffprobe: Path, *, runner: Callable | None = None
) -> None:
    """Verify the local decoders, encoders, filters, probing, and canonical WAV path."""
    ffmpeg = Path(ffmpeg).resolve()
    ffprobe = Path(ffprobe).resolve()
    for binary in (ffmpeg, ffprobe):
        if not binary.is_file():
            raise RuntimeError(f"Required FFmpeg tool does not exist: {binary}")

    decoder_listing = _run(
        (ffmpeg, "-hide_banner", "-decoders"), runner=runner
    )
    decoder_text = decoder_listing.stdout + decoder_listing.stderr
    if not re.search(r"\bmp3(?:float)?\b", decoder_text):
        raise RuntimeError("The FFmpeg build does not register an MP3 decoder")

    with tempfile.TemporaryDirectory(prefix="audiotranscriber-ffmpeg-smoke-") as temp_name:
        temp_dir = Path(temp_name)
        synthetic_wav = temp_dir / "synthetic.wav"
        _write_synthetic_wav(synthetic_wav)
        _probe_audio(ffprobe, synthetic_wav, runner=runner)

        formats = (
            ("aac", "ipod", "m4a", "aac", ()),
            ("vorbis", "ogg", "ogg", "vorbis", ("-ac", "2", "-strict", "-2")),
            ("flac", "flac", "flac", "flac", ()),
        )
        for encoder, muxer, suffix, expected_codec, encoder_options in formats:
            encoded = temp_dir / f"roundtrip.{suffix}"
            _run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    synthetic_wav,
                    "-vn",
                    *encoder_options,
                    "-c:a",
                    encoder,
                    "-f",
                    muxer,
                    encoded,
                ],
                runner=runner,
            )
            if not encoded.is_file() or not encoded.stat().st_size:
                raise RuntimeError(f"FFmpeg did not produce the expected {suffix.upper()} test file")
            stream = _probe_audio(ffprobe, encoded, runner=runner)
            if stream.get("codec_name") != expected_codec:
                raise RuntimeError(
                    f"Expected {expected_codec} in {encoded.name}, got {stream.get('codec_name')!r}"
                )
            _run(
                (ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", encoded, "-f", "null", "-"),
                runner=runner,
            )

        silence_result = _run(
            (
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-v",
                "info",
                "-i",
                synthetic_wav,
                "-af",
                "silencedetect=noise=-45dB:d=0.2",
                "-f",
                "null",
                "-",
            ),
            runner=runner,
        )
        if "silence_start:" not in silence_result.stderr:
            raise RuntimeError("FFmpeg silence detection did not identify the synthetic quiet section")

        canonical_wav = temp_dir / "canonical.wav"
        _run(
            (
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                synthetic_wav,
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                canonical_wav,
            ),
            runner=runner,
        )
        stream = _probe_audio(ffprobe, canonical_wav, runner=runner)
        if (
            stream.get("codec_name") != "pcm_s16le"
            or stream.get("sample_rate") != str(SAMPLE_RATE)
            or stream.get("channels") != 1
        ):
            raise RuntimeError(
                "Canonical output must be mono 16 kHz pcm_s16le; FFprobe reported "
                f"{stream!r}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_bin = Path(__file__).resolve().parent / "bin"
    parser.add_argument("--ffmpeg", type=Path, default=default_bin / "ffmpeg.exe")
    parser.add_argument("--ffprobe", type=Path, default=default_bin / "ffprobe.exe")
    args = parser.parse_args(argv)
    try:
        run_smoke_test(args.ffmpeg, args.ffprobe)
    except Exception as exc:
        print(f"FFmpeg smoke test failed: {exc}", file=sys.stderr)
        return 1
    print("FFmpeg synthetic-media smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
