from __future__ import annotations

import hashlib
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packaging"))

import fetch_ffmpeg
import smoke_test_ffmpeg


SOURCE_BYTES = b"verified FFmpeg source archive fixture"
SIGNATURE_BYTES = b"detached signature fixture"
SOURCE_NAME = "ffmpeg-9.0.2.tar.xz"
SIGNATURE_NAME = SOURCE_NAME + ".asc"


def _set_fixture_pin(monkeypatch):
    monkeypatch.setattr(
        fetch_ffmpeg,
        "SOURCE_SHA256",
        hashlib.sha256(SOURCE_BYTES).hexdigest(),
        raising=False,
    )
    monkeypatch.setattr(fetch_ffmpeg, "SOURCE_ARCHIVE_NAME", SOURCE_NAME, raising=False)
    monkeypatch.setattr(fetch_ffmpeg, "SOURCE_SIGNATURE_NAME", SIGNATURE_NAME, raising=False)


def test_source_pin_matches_official_signed_release():
    assert fetch_ffmpeg.FFMPEG_VERSION == "9.0.2"
    assert fetch_ffmpeg.SOURCE_URL == "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz"
    assert fetch_ffmpeg.SOURCE_SHA256 == (
        "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
    )
    assert fetch_ffmpeg.RELEASE_KEY_FINGERPRINT == (
        "FCF986EA15E6E293A5644F10B4322F04D67658D8"
    )


def test_fetch_downloads_pinned_source_and_signature_atomically(tmp_path, monkeypatch):
    _set_fixture_pin(monkeypatch)
    responses = iter((io.BytesIO(SOURCE_BYTES), io.BytesIO(SIGNATURE_BYTES)))
    urls = []

    def open_url(url, *, timeout):
        urls.append((url, timeout))
        return next(responses)

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", open_url)

    source, signature = fetch_ffmpeg.fetch(tmp_path / "source")

    assert source.name == SOURCE_NAME
    assert source.read_bytes() == SOURCE_BYTES
    assert signature.name == SIGNATURE_NAME
    assert signature.read_bytes() == SIGNATURE_BYTES
    assert [url for url, _timeout in urls] == [
        "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz",
        "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz.asc",
    ]
    assert all(timeout > 0 for _url, timeout in urls)


def test_cached_source_is_rehashed_before_reuse(tmp_path, monkeypatch):
    _set_fixture_pin(monkeypatch)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / SOURCE_NAME
    signature = source_dir / SIGNATURE_NAME
    source.write_bytes(SOURCE_BYTES)
    signature.write_bytes(SIGNATURE_BYTES)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("a valid pinned source cache must not download")

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", unexpected_download)

    assert fetch_ffmpeg.fetch(source_dir) == (source, signature)


def test_tampered_cached_source_fails_closed_without_reuse(tmp_path, monkeypatch):
    _set_fixture_pin(monkeypatch)
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / SOURCE_NAME).write_bytes(b"tampered bytes")
    (source_dir / SIGNATURE_NAME).write_bytes(SIGNATURE_BYTES)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("a tampered cached archive must fail, not be reused")

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", unexpected_download)

    with pytest.raises(RuntimeError, match="SHA-256"):
        fetch_ffmpeg.fetch(source_dir)


def test_missing_signature_does_not_leave_a_partial_source(tmp_path, monkeypatch):
    _set_fixture_pin(monkeypatch)
    calls = []

    def open_url(url, *, timeout):
        calls.append(url)
        if url.endswith(".asc"):
            raise OSError("signature unavailable")
        return io.BytesIO(SOURCE_BYTES)

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", open_url)
    source_dir = tmp_path / "source"

    with pytest.raises(RuntimeError, match="signature"):
        fetch_ffmpeg.fetch(source_dir)

    assert calls == [
        "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz",
        "https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz.asc",
    ]
    assert not (source_dir / SOURCE_NAME).exists()


def test_build_script_pins_source_and_lgpl_feature_set():
    script_path = REPO_ROOT / "packaging" / "build_ffmpeg.sh"
    script = script_path.read_text(encoding="utf-8")

    assert f"FFMPEG_VERSION={fetch_ffmpeg.FFMPEG_VERSION}" in script
    assert f"SOURCE_URL={fetch_ffmpeg.SOURCE_URL}" in script
    assert f"SOURCE_SHA256={fetch_ffmpeg.SOURCE_SHA256}" in script
    assert f"RELEASE_KEY_FINGERPRINT={fetch_ffmpeg.RELEASE_KEY_FINGERPRINT}" in script
    for option in (
        "--disable-everything",
        "--disable-gpl",
        "--disable-version3",
        "--disable-nonfree",
        "--disable-autodetect",
        "--disable-network",
        "--enable-shared",
        "--disable-static",
        "--enable-w32threads",
        "--extra-ldflags=-static-libgcc",
        "--enable-demuxer=mov,mp3,wav,flac,ogg",
        "--enable-protocol=file",
        "--enable-filter=silencedetect",
        "--enable-decoder=aac,aac_fixed,alac,mp3,mp3float,ac3,eac3,flac,opus,vorbis,pcm_u8,pcm_s16le,pcm_s16be,pcm_s24le,pcm_s24be,pcm_s32le,pcm_f32le,pcm_f64le",
        "--enable-encoder=pcm_s16le,aac,vorbis,flac",
        "--enable-muxer=wav,ipod,ogg,flac,null",
    ):
        assert option in script
    assert "--status-fd 1" in script and '--verify "$source_signature"' in script
    assert "VALIDSIG" in script
    assert not re.search(r"--enable-(?:gpl|version3|nonfree)\b", script)
    assert "--enable-lib" not in script


def test_build_script_has_valid_bash_syntax():
    script = REPO_ROOT / "packaging" / "build_ffmpeg.sh"
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_ffmpeg_smoke_script_covers_local_media_and_app_features():
    smoke_script = REPO_ROOT / "packaging" / "smoke_test_ffmpeg.py"
    assert smoke_script.is_file()
    source = smoke_script.read_text(encoding="utf-8")
    for expected in (
        "TemporaryDirectory",
        "wave.open",
        "ffmpeg.exe",
        "ffprobe.exe",
        "silencedetect=noise=",
        "aac",
        "vorbis",
        "flac",
        "pcm_s16le",
        '"sample_rate"',
        '"channels"',
        "16_000",
        "mp3",
    ):
        assert expected in source


def test_vorbis_smoke_roundtrip_uses_native_encoder_compatibility_flags(tmp_path):
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffprobe = tmp_path / "ffprobe.exe"
    ffmpeg.write_bytes(b"test binary")
    ffprobe.write_bytes(b"test binary")
    commands = []

    def fake_runner(command, *, capture_output, text, check):
        command = [str(part) for part in command]
        commands.append(command)
        if Path(command[0]).name == "ffprobe.exe":
            media = Path(command[-1])
            codec = {
                ".wav": "pcm_s16le",
                ".m4a": "aac",
                ".ogg": "vorbis",
                ".flac": "flac",
            }[media.suffix]
            stdout = '{"streams":[{"codec_name":"%s","sample_rate":"16000","channels":1}]}' % codec
            return subprocess.CompletedProcess(command, 0, stdout, "")
        if "-decoders" in command:
            return subprocess.CompletedProcess(command, 0, " A....D mp3 MP3 decoder\n", "")
        if "-af" in command:
            return subprocess.CompletedProcess(command, 0, "", "silence_start: 0.75\n")
        if command[-1] != "-":
            Path(command[-1]).write_bytes(b"synthetic encoded output")
        return subprocess.CompletedProcess(command, 0, "", "")

    smoke_test_ffmpeg.run_smoke_test(ffmpeg, ffprobe, runner=fake_runner)

    vorbis_command = next(
        command
        for command in commands
        if "-c:a" in command and command[command.index("-c:a") + 1] == "vorbis"
    )
    assert vorbis_command[vorbis_command.index("-ac") + 1] == "2"
    assert vorbis_command[vorbis_command.index("-strict") + 1] == "-2"
