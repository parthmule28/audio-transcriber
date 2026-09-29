import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from audio_transcriber.audio import (
    MediaInfo,
    detect_quiet_midpoints,
    extract_chunk,
    probe,
    resolve_binary,
)
from audio_transcriber.errors import AudioPreparationError, FfmpegMissingError, NoAudioStreamError


@pytest.fixture
def real_ffmpeg():
    return shutil.which("ffmpeg")


def make_sine_wav(path: Path, *, seconds: int) -> Path:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=" + str(seconds), "-y", str(path)],
        capture_output=True, text=True, check=True,
    )
    return path


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_probe_reports_duration_and_audio_stream(tmp_path, real_ffmpeg):
    media = make_sine_wav(tmp_path / "tone.wav", seconds=5)
    info = probe(media)
    assert info.has_audio is True
    assert info.duration == pytest.approx(5.0, abs=0.3)
    assert info.codec_name == "pcm_s16le"
    assert info.sample_rate == 44100
    assert info.channels == 1


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg unavailable")
def test_extract_chunk_produces_canonical_wav(tmp_path, real_ffmpeg):
    media = make_sine_wav(tmp_path / "tone.wav", seconds=10)
    before = media.read_bytes()
    out = extract_chunk(media, start=2.0, duration=3.0, out_path=tmp_path / "chunks" / "c0.wav")
    assert out == tmp_path / "chunks" / "c0.wav"
    assert out.exists()
    assert media.read_bytes() == before
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=sample_rate,channels,codec_name",
         "-of", "json", str(out)], capture_output=True, text=True, check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    assert stream["codec_name"] == "pcm_s16le"
    assert stream["sample_rate"] == "16000"
    assert stream["channels"] == 1


def fake_process(monkeypatch, *, stdout="", stderr="", returncode=0):
    calls = []

    def run(argv, *, capture_output, text, check):
        assert isinstance(argv, list)
        assert capture_output and text and check is False
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr("audio_transcriber.audio.subprocess.run", run)
    return calls


def test_probe_raises_no_audio_stream_for_video_only_input(tmp_path, monkeypatch):
    calls = fake_process(monkeypatch, stdout=json.dumps({
        "format": {"duration": "5.0", "format_name": "matroska"},
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
    }))
    source = tmp_path / "video only.mp4"
    with pytest.raises(NoAudioStreamError, match="audio"):
        probe(source, ffprobe=Path("fake-ffprobe"))
    assert calls == [["fake-ffprobe", "-v", "error", "-print_format", "json",
                      "-show_format", "-show_streams", str(source)]]


@pytest.mark.parametrize("output", ["not json", json.dumps({"format": {"duration": "oops"},
                                                              "streams": [{"codec_type": "audio"}]}),
                                     json.dumps({"format": {"duration": "0"},
                                                 "streams": [{"codec_type": "audio"}]})])
def test_probe_raises_on_unparseable_output(monkeypatch, output):
    fake_process(monkeypatch, stdout=output)
    with pytest.raises(AudioPreparationError):
        probe(Path("input.wav"), ffprobe=Path("fake-ffprobe"))


def test_probe_raises_on_failed_process(monkeypatch):
    fake_process(monkeypatch, stderr="private path or key", returncode=1)
    with pytest.raises(AudioPreparationError) as exc:
        probe(Path("input.wav"), ffprobe=Path("fake-ffprobe"))
    assert "private path or key" not in str(exc.value)


def test_probe_uses_first_audio_stream(monkeypatch):
    fake_process(monkeypatch, stdout=json.dumps({
        "format": {"duration": "4.5", "format_name": "mov,mp4"},
        "streams": [{"codec_type": "video"}, {"codec_type": "audio", "codec_name": "aac",
                                            "sample_rate": "48000", "channels": 2}],
    }))
    info = probe(Path("sample.mp4"), ffprobe=Path("fake-ffprobe"))
    assert info == (4.5, True, "mov,mp4", "aac", 48000, 2)


def test_resolve_binary_prefers_bundled_directory(tmp_path, monkeypatch):
    bundled = tmp_path / "ffmpeg.exe"
    bundled.write_bytes(b"fake executable")
    monkeypatch.setattr("audio_transcriber.audio.shutil.which", lambda name: "/other/ffmpeg")
    monkeypatch.setattr("audio_transcriber.audio.os.access", lambda path, mode: True)
    assert resolve_binary("ffmpeg", bundled_dir=tmp_path) == bundled


def test_resolve_binary_defaults_to_frozen_executable_directory(tmp_path, monkeypatch):
    bundled = tmp_path / "ffprobe.exe"
    bundled.write_bytes(b"fake executable")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "transcriber.exe"))
    monkeypatch.setattr("audio_transcriber.audio.os.access", lambda path, mode: True)
    assert resolve_binary("ffprobe") == bundled


def test_resolve_binary_falls_back_to_path(monkeypatch):
    monkeypatch.setattr("audio_transcriber.audio.shutil.which", lambda name: "/usr/bin/ffprobe")
    assert resolve_binary("ffprobe") == Path("/usr/bin/ffprobe")


def test_resolve_binary_raises_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("audio_transcriber.audio.shutil.which", lambda name: None)
    with pytest.raises(FfmpegMissingError) as exc:
        resolve_binary("ffprobe", bundled_dir=tmp_path)
    assert "ffprobe" in exc.value.user_message.lower()
    assert "release ZIP" in exc.value.user_message


def test_detect_quiet_midpoints_returns_sorted_midpoints(monkeypatch):
    duration = 10.0
    calls = fake_process(monkeypatch, stderr=(
        "[silencedetect] silence_start: 7.0\n"
        "[silencedetect] silence_end: 9.0 | silence_duration: 2.0\n"
        "[silencedetect] silence_start: 1.0\n"
        "[silencedetect] silence_end: 3.0 | silence_duration: 2.0\n"
    ))
    monkeypatch.setattr("audio_transcriber.audio.probe", lambda source: MediaInfo(duration, True, "wav", None, None, None))
    result = detect_quiet_midpoints(Path("sample.wav"), noise_db=-35, min_duration=0.4,
                                    ffmpeg=Path("fake-ffmpeg"))
    assert result == [2.0, 8.0]
    assert all(0.0 <= midpoint <= duration for midpoint in result)
    assert calls == [["fake-ffmpeg", "-nostdin", "-hide_banner", "-i", "sample.wav", "-vn",
                      "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-"]]


def test_detect_quiet_midpoints_bounds_completed_silences_to_media_duration(monkeypatch):
    duration = 10.0
    fake_process(monkeypatch, stderr=(
        "[silencedetect] silence_start: 8.0\n"
        "[silencedetect] silence_end: 20.0 | silence_duration: 12.0\n"
        "[silencedetect] silence_start: 1.0\n"
        "[silencedetect] silence_end: 3.0 | silence_duration: 2.0\n"
        "[silencedetect] silence_start: 12.0\n"
        "[silencedetect] silence_end: 15.0 | silence_duration: 3.0\n"
    ))
    monkeypatch.setattr("audio_transcriber.audio.probe", lambda source: MediaInfo(duration, True, "wav", None, None, None))
    result = detect_quiet_midpoints(Path("sample.wav"), noise_db=-35, min_duration=0.4,
                                    ffmpeg=Path("fake-ffmpeg"))
    assert result == [2.0, 9.0]
    assert all(0.0 <= midpoint <= duration for midpoint in result)


def test_detect_quiet_midpoints_closes_trailing_silence_at_duration(monkeypatch):
    fake_process(monkeypatch, stderr="[silencedetect] silence_start: 8.0\n")
    monkeypatch.setattr("audio_transcriber.audio.probe", lambda source: MediaInfo(10.0, True, "wav", None, None, None))
    assert detect_quiet_midpoints(Path("sample.wav"), noise_db=-30, min_duration=0.5,
                                  ffmpeg=Path("fake-ffmpeg")) == [9.0]


def test_detect_quiet_midpoints_returns_empty_without_silence(monkeypatch):
    fake_process(monkeypatch, stderr="no silence here")
    assert detect_quiet_midpoints(Path("sample.wav"), noise_db=-30, min_duration=0.5,
                                  ffmpeg=Path("fake-ffmpeg")) == []


def test_extract_chunk_reports_failure_without_leaking_stderr(tmp_path, monkeypatch):
    calls = fake_process(monkeypatch, stderr="sensitive location", returncode=1)
    source = tmp_path / "source.wav"
    source.write_bytes(b"untouched")
    with pytest.raises(AudioPreparationError) as exc:
        extract_chunk(source, start=2, duration=3, out_path=tmp_path / "new" / "chunk.wav",
                      ffmpeg=Path("fake-ffmpeg"))
    assert "sensitive location" not in str(exc.value)
    assert source.read_bytes() == b"untouched"
    assert (tmp_path / "new").is_dir()
    assert calls == [["fake-ffmpeg", "-nostdin", "-hide_banner", "-y", "-ss", "2", "-t", "3",
                      "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                      "-f", "wav", str(tmp_path / "new" / "chunk.wav")]]
