"""FFmpeg-based media inspection, silence detection, and WAV preparation."""

import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

from .constants import CANONICAL_SAMPLE_RATE
from .errors import AudioPreparationError, FfmpegMissingError, NoAudioStreamError


class MediaInfo(NamedTuple):
    duration: float
    has_audio: bool
    format_name: str
    codec_name: str | None
    sample_rate: int | None
    channels: int | None


def resolve_binary(name: str, *, bundled_dir: Path | None = None) -> Path:
    if bundled_dir is None and getattr(sys, "frozen", False):
        bundled_dir = Path(sys.executable).parent
    if bundled_dir is not None:
        for candidate in (bundled_dir / (name + ".exe"), bundled_dir / name):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    error = FfmpegMissingError(f"Required binary {name} was not found")
    error.user_message = f"{name} is missing. Please re-download the release ZIP."
    raise error


def probe(source: Path, *, ffprobe: Path | None = None) -> MediaInfo:
    binary = ffprobe if ffprobe is not None else resolve_binary("ffprobe")
    try:
        result = subprocess.run(
            [str(binary), "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", str(source)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise AudioPreparationError("Could not inspect media")
        data = json.loads(result.stdout)
        streams = data["streams"]
        stream = next((item for item in streams if item.get("codec_type") == "audio"), None)
        if stream is None:
            raise NoAudioStreamError("The selected file does not contain an audio track")
        format_data = data["format"]
        duration = float(format_data["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Invalid duration")
        return MediaInfo(
            duration, True, format_data.get("format_name", ""), stream.get("codec_name"),
            int(stream["sample_rate"]) if stream.get("sample_rate") else None,
            int(stream["channels"]) if stream.get("channels") is not None else None,
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AudioPreparationError("Could not inspect media metadata") from exc


_SILENCE_EVENT = re.compile(r"silence_(start|end):\s*([0-9]+(?:\.[0-9]+)?)")


def detect_quiet_midpoints(
    source: Path, *, noise_db: float, min_duration: float, ffmpeg: Path | None = None,
) -> list[float]:
    binary = ffmpeg if ffmpeg is not None else resolve_binary("ffmpeg")
    try:
        result = subprocess.run(
            [str(binary), "-nostdin", "-hide_banner", "-i", str(source), "-vn", "-af",
             f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise AudioPreparationError("Could not detect quiet sections") from exc
    if result.returncode != 0:
        raise AudioPreparationError("Could not detect quiet sections")

    intervals: list[tuple[float, float]] = []
    start: float | None = None
    for match in _SILENCE_EVENT.finditer(result.stderr):
        position = float(match.group(2))
        if match.group(1) == "start":
            start = position
        elif start is not None:
            if position >= start:
                intervals.append((start, position))
            start = None
    if not intervals and start is None:
        return []
    duration = probe(source).duration
    if start is not None:
        intervals.append((start, duration))
    return sorted(
        (max(0.0, begin) + min(end, duration)) / 2
        for begin, end in intervals
        if 0.0 <= begin <= duration and end >= begin
    )


def extract_chunk(
    source: Path, start: float, duration: float, out_path: Path, *, ffmpeg: Path | None = None,
) -> Path:
    binary = ffmpeg if ffmpeg is not None else resolve_binary("ffmpeg")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(binary), "-nostdin", "-hide_banner", "-y", "-ss", str(start), "-t",
             str(duration), "-i", str(source), "-vn", "-ac", "1", "-ar",
             str(CANONICAL_SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(out_path)],
            capture_output=True, text=True, check=False,
        )
    except OSError as exc:
        raise AudioPreparationError("Could not extract audio chunk") from exc
    if result.returncode != 0:
        raise AudioPreparationError("Could not extract audio chunk")
    return out_path
