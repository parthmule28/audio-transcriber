"""FFmpeg-based media inspection, silence detection, and WAV preparation."""

import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import NamedTuple

from .constants import CANONICAL_SAMPLE_RATE
from .errors import AudioPreparationError, CancelledError, FfmpegMissingError, NoAudioStreamError


FFMPEG_PROCESS_TIMEOUT_SECONDS = 300.0
_PROCESS_POLL_INTERVAL_SECONDS = 0.1
_PROCESS_TERMINATE_GRACE_SECONDS = 0.5


class MediaInfo(NamedTuple):
    duration: float
    has_audio: bool
    format_name: str
    codec_name: str | None
    sample_rate: int | None
    channels: int | None


def _terminate_and_reap(process: subprocess.Popen) -> None:
    """Stop a child and drain its pipes so it cannot outlive the caller."""
    if process.poll() is None:
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.communicate(timeout=_PROCESS_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        process.communicate()


def _run_bounded_process(
    args: list[str],
    *,
    timeout: float,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    """Run an argument-list child with a hard deadline and cooperative cancel."""
    if timeout <= 0:
        raise ValueError("process timeout must be positive")
    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event is not None and cancel_event.is_set():
            _terminate_and_reap(process)
            raise CancelledError("FFmpeg processing was cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_and_reap(process)
            raise subprocess.TimeoutExpired(args, timeout)
        try:
            stdout, stderr = process.communicate(
                timeout=min(_PROCESS_POLL_INTERVAL_SECONDS, remaining)
            )
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


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


def probe(
    source: Path,
    *,
    ffprobe: Path | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = FFMPEG_PROCESS_TIMEOUT_SECONDS,
) -> MediaInfo:
    binary = ffprobe if ffprobe is not None else resolve_binary("ffprobe")
    try:
        result = _run_bounded_process(
            [str(binary), "-v", "error", "-print_format", "json", "-show_format",
             "-show_streams", str(source)],
            timeout=timeout,
            cancel_event=cancel_event,
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
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AudioPreparationError("Could not inspect media metadata") from exc


_SILENCE_EVENT = re.compile(r"silence_(start|end):\s*([0-9]+(?:\.[0-9]+)?)")


def detect_quiet_midpoints(
    source: Path,
    *,
    noise_db: float,
    min_duration: float,
    ffmpeg: Path | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = FFMPEG_PROCESS_TIMEOUT_SECONDS,
) -> list[float]:
    binary = ffmpeg if ffmpeg is not None else resolve_binary("ffmpeg")
    try:
        result = _run_bounded_process(
            [str(binary), "-nostdin", "-hide_banner", "-i", str(source), "-vn", "-af",
             f"silencedetect=noise={noise_db}dB:d={min_duration}", "-f", "null", "-"],
            timeout=timeout,
            cancel_event=cancel_event,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
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
    duration = probe(source, cancel_event=cancel_event, timeout=timeout).duration
    if start is not None:
        intervals.append((start, duration))
    return sorted(
        (max(0.0, begin) + min(end, duration)) / 2
        for begin, end in intervals
        if 0.0 <= begin <= duration and end >= begin
    )


def extract_chunk(
    source: Path,
    start: float,
    duration: float,
    out_path: Path,
    *,
    ffmpeg: Path | None = None,
    cancel_event: threading.Event | None = None,
    timeout: float = FFMPEG_PROCESS_TIMEOUT_SECONDS,
) -> Path:
    binary = ffmpeg if ffmpeg is not None else resolve_binary("ffmpeg")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = _run_bounded_process(
            [str(binary), "-nostdin", "-hide_banner", "-y", "-ss", str(start), "-t",
             str(duration), "-i", str(source), "-vn", "-ac", "1", "-ar",
             str(CANONICAL_SAMPLE_RATE), "-c:a", "pcm_s16le", "-f", "wav", str(out_path)],
            timeout=timeout,
            cancel_event=cancel_event,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioPreparationError("Could not extract audio chunk") from exc
    if result.returncode != 0:
        raise AudioPreparationError("Could not extract audio chunk")
    return out_path
