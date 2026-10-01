from __future__ import annotations

import ast
import hashlib
import io
import runpy
import re
import shutil
import sys
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packaging"))

import build_release
import license_material
from audio_transcriber import __version__


def _full_text(title: str) -> bytes:
    terms = "Permission is granted subject to the conditions and disclaimers below.\n"
    return (title + "\n\n" + terms * 24 + "\nAll rights reserved.\n").encode()


def _source_archive_bytes() -> bytes:
    stream = io.BytesIO()
    license_content = _full_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1")
    with tarfile.open(fileobj=stream, mode="w:xz", format=tarfile.USTAR_FORMAT) as archive:
        for name, content in (
            ("ffmpeg-9.0.2/configure", b"#!/bin/sh\n"),
            ("ffmpeg-9.0.2/COPYING.LGPLv2.1", license_content),
            ("ffmpeg-9.0.2/libavcodec/codec.c", b"int codec_fixture(void) { return 0; }\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


_SOURCE_ARCHIVE = _source_archive_bytes()
_SOURCE_HASH = hashlib.sha256(_SOURCE_ARCHIVE).hexdigest()
_FFMPEG_RUNTIME = {
    "ffmpeg.exe": b"ffmpeg",
    "ffprobe.exe": b"ffprobe",
    "avcodec-61.dll": b"codec dll",
    "avutil-59.dll": b"util dll",
}
_FFMPEG_BUILD_SCRIPT = b"#!/usr/bin/env bash\n# reproducible UCRT64 test recipe\n"
_RUNTIME_HASHES = "\n".join(
    f"{hashlib.sha256(content).hexdigest()}  {name}"
    for name, content in _FFMPEG_RUNTIME.items()
)
_FFMPEG_LICENSE = _full_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 2.1")
_FFMPEG_SIGNATURE = b"detached signature fixture"
_FFMPEG_RELEASE_KEY = b"FFmpeg release public key fixture"
_FFMPEG_FETCHER = b"# pinned source-fetch fixture\n"
_SOURCE_OFFER = _full_text(
    "FFmpeg 9.0.2 exact corresponding source included with this distribution\n"
    f"Source archive SHA-256: {_SOURCE_HASH}\n"
    "Source archive: ffmpeg-9.0.2.tar.xz\n"
    "The detached signature, signing key, build recipe, source-fetch script, license, "
    "runtime hashes, and GCC runtime notices are included in the same ZIP."
)
_FFMPEG_BUILD_METADATA = (
    "FFmpeg source-built Windows runtime metadata\n"
    "FFmpeg version: 9.0.2\n"
    "Source URL: https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz\n"
    "Source archive: ffmpeg-9.0.2.tar.xz\n"
    f"Source archive SHA-256: {_SOURCE_HASH}\n"
    "Source signature: ffmpeg-9.0.2.tar.xz.asc\n"
    "Signature result: VALID\n"
    "Release key fingerprint: FCF986EA15E6E293A5644F10B4322F04D67658D8\n"
    f"Source signature SHA-256: {hashlib.sha256(_FFMPEG_SIGNATURE).hexdigest()}\n"
    f"Release key SHA-256: {hashlib.sha256(_FFMPEG_RELEASE_KEY).hexdigest()}\n"
    f"FFmpeg license SHA-256: {hashlib.sha256(_FFMPEG_LICENSE).hexdigest()}\n"
    f"Source fetcher SHA-256: {hashlib.sha256(_FFMPEG_FETCHER).hexdigest()}\n"
    f"Source offer SHA-256: {hashlib.sha256(_SOURCE_OFFER).hexdigest()}\n"
    "Configure arguments:\n"
    "  --disable-everything\n"
    "  --disable-gpl\n"
    "  --disable-version3\n"
    "  --disable-nonfree\n"
    "  --disable-autodetect\n"
    "  --disable-network\n"
    "  --enable-shared\n"
    "  --disable-static\n"
    "Runtime-file SHA-256:\n"
    f"{_RUNTIME_HASHES}\n"
    f"Build script SHA-256: {hashlib.sha256(_FFMPEG_BUILD_SCRIPT).hexdigest()}\n"
)
_RELEASE_LICENSES = {
    "BUILD-METADATA.txt": b"Collected package versions and provenance (fixture)\n",
    "FFmpeg/LICENSE-LGPL-2.1.txt": _FFMPEG_LICENSE,
    "FFmpeg/BUILD-METADATA.txt": _FFMPEG_BUILD_METADATA.encode(),
    "FFmpeg/SOURCE-OFFER.md": _SOURCE_OFFER,
    "FFmpeg/Source/ffmpeg-9.0.2.tar.xz": _SOURCE_ARCHIVE,
    "FFmpeg/Source/ffmpeg-9.0.2.tar.xz.asc": _FFMPEG_SIGNATURE,
    "FFmpeg/Source/ffmpeg-release-key.asc": _FFMPEG_RELEASE_KEY,
    "FFmpeg/Source/build_ffmpeg.sh": _FFMPEG_BUILD_SCRIPT,
    "FFmpeg/Source/fetch_ffmpeg.py": _FFMPEG_FETCHER,
    "FFmpeg/GCC-RUNTIME-LICENSES/gcc/COPYING.RUNTIME": _full_text(
        "GCC Runtime Library Exception"
    ),
    "PySide6/LGPL-3.0-only.txt": _full_text("GNU LESSER GENERAL PUBLIC LICENSE Version 3"),
    "PySide6/Qt-GPL-exception-1.0.txt": _full_text("Qt GPL exception"),
    "Qt/LGPL-3.0-only.txt": _full_text("Qt LGPL Version 3"),
    "httpx/LICENSE.md": _full_text("BSD 3-Clause License"),
    "keyring/LICENSE": _full_text("MIT License"),
    "Python/LICENSE.txt": _full_text("Python Software Foundation License"),
    "Python-Packages.md": _full_text("Generated package inventory including PyInstaller bootloader"),
}


@pytest.fixture(autouse=True)
def fake_release_license_material(monkeypatch):
    monkeypatch.setattr(license_material, "FFMPEG_SOURCE_SHA256", _SOURCE_HASH)

    def collect(destination, *, repo_root):
        destination = Path(destination)
        for relative_path, content in _RELEASE_LICENSES.items():
            target = destination / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    monkeypatch.setattr(
        build_release,
        "collect_release_license_material",
        collect,
        raising=False,
    )


def fake_pyinstaller_runner(argv, *, cwd):
    assert isinstance(argv, (list, tuple))
    assert Path(cwd) == REPO_ROOT
    dist_path = Path(argv[argv.index("--distpath") + 1])
    app_dir = dist_path / "AudioTranscriber"
    licenses_dir = app_dir / "LICENSES"
    licenses_dir.mkdir(parents=True)
    shutil.copytree(REPO_ROOT / "LICENSES", licenses_dir, dirs_exist_ok=True)
    (app_dir / "AudioTranscriber.exe").write_bytes(b"app")
    for filename, content in _FFMPEG_RUNTIME.items():
        (app_dir / filename).write_bytes(content)

    # A build directory may contain project or developer data; the release ZIP must not.
    (app_dir / "sample.wav").write_bytes(b"audio")
    (app_dir / "nested").mkdir()
    (app_dir / "nested" / "recording.M4A").write_bytes(b"audio")
    (app_dir / "nested" / "recording.mp3").write_bytes(b"audio")
    (app_dir / ".env").write_text("TOKEN=secret", encoding="utf-8")
    (app_dir / "API_KEY_BACKUP.json").write_text("secret", encoding="utf-8")
    key_dir = app_dir / "private-key-cache"
    key_dir.mkdir()
    (key_dir / "metadata.json").write_text("secret", encoding="utf-8")


def test_zip_contains_expected_layout_and_name(tmp_path):
    zip_path = build_release.build(
        __version__, output_dir=tmp_path, repo_root=REPO_ROOT, runner=fake_pyinstaller_runner
    )

    assert zip_path == tmp_path / f"AudioTranscriber-v{__version__}-win-x64.zip"
    names = build_release.zip_contents(zip_path)
    assert "AudioTranscriber/AudioTranscriber.exe" in names
    assert "AudioTranscriber/ffmpeg.exe" in names
    assert "AudioTranscriber/ffprobe.exe" in names
    assert "AudioTranscriber/LICENSES/README.md" in names
    assert "AudioTranscriber/LICENSES/THIRD-PARTY-NOTICES.md" in names
    assert "AudioTranscriber/LICENSES/FFmpeg/SOURCE-OFFER.md" in names
    assert "AudioTranscriber/LICENSES/FFmpeg/Source/ffmpeg-9.0.2.tar.xz" in names
    assert "AudioTranscriber/LICENSES/FFmpeg/Source/ffmpeg-9.0.2.tar.xz.asc" in names
    assert "AudioTranscriber/LICENSES/FFmpeg/Source/ffmpeg-release-key.asc" in names
    assert "AudioTranscriber/LICENSES/FFmpeg/Source/build_ffmpeg.sh" in names
    assert "AudioTranscriber/LICENSES/Python-Packages.md" in names
    with zipfile.ZipFile(zip_path) as archive:
        for relative_path, expected_content in _RELEASE_LICENSES.items():
            member = f"AudioTranscriber/LICENSES/{relative_path}"
            assert member in names
            assert archive.read(member) == expected_content
            assert archive.getinfo(member).file_size > 0
    assert names == sorted(names)


def test_third_party_notice_names_all_bundled_components_and_says_texts_are_not_included():
    notices = (REPO_ROOT / "LICENSES" / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")

    for component in ("FFmpeg and FFprobe", "PySide6", "Qt", "httpx", "keyring", "Python"):
        assert component in notices
    for license_name in ("LGPL v2.1", "LGPL v3", "BSD 3-Clause", "MIT", "PSF"):
        assert license_name in notices
    assert "full license texts" in notices.lower()


def test_zip_root_folder_is_named_for_the_app(tmp_path):
    zip_path = build_release.build(
        __version__, output_dir=tmp_path, repo_root=REPO_ROOT, runner=fake_pyinstaller_runner
    )

    assert all(name.startswith("AudioTranscriber/") for name in build_release.zip_contents(zip_path))


def test_zip_excludes_media_environment_and_key_files_except_keyring_license_material(tmp_path):
    zip_path = build_release.build(
        __version__, output_dir=tmp_path, repo_root=REPO_ROOT, runner=fake_pyinstaller_runner
    )

    forbidden = (".wav", ".m4a", ".mp3", ".env")
    names = build_release.zip_contents(zip_path)
    assert not [name for name in names if name.lower().endswith(forbidden)]
    assert not [name for name in names if ".env/" in name.lower() or ".env." in name.lower()]
    assert not [
        name
        for name in names
        if any("key" in component.lower() for component in Path(name).parts)
        and not name.startswith("AudioTranscriber/LICENSES/keyring/")
        and name != "AudioTranscriber/LICENSES/FFmpeg/Source/ffmpeg-release-key.asc"
    ]
    assert "AudioTranscriber/LICENSES/keyring/LICENSE" in names


def test_build_rejects_tag_or_input_version_drift(tmp_path):
    with pytest.raises(ValueError, match="package version"):
        build_release.build(
            "9.9.9", output_dir=tmp_path, repo_root=REPO_ROOT, runner=fake_pyinstaller_runner
        )

    assert not list(tmp_path.glob("AudioTranscriber-v*-win-x64.zip"))


def _execute_spec(spec_text: str, packaging_dir: Path):
    packaging_dir.mkdir(parents=True, exist_ok=True)
    spec_path = packaging_dir / "AudioTranscriber.spec"
    spec_path.write_text(spec_text, encoding="utf-8")
    calls = {}

    class FakeAnalysis:
        scripts = []
        pure = []
        binaries = []
        datas = []

    def analysis(*args, **kwargs):
        calls["analysis"] = kwargs
        return FakeAnalysis()

    def executable(*args, **kwargs):
        calls["exe"] = kwargs
        return object()

    def collect(*args, **kwargs):
        calls["collect"] = kwargs
        return object()

    globals_for_spec = {
        "SPECPATH": str(packaging_dir),
        "Analysis": analysis,
        "PYZ": lambda *args, **kwargs: object(),
        "EXE": executable,
        "COLLECT": collect,
    }
    runpy.run_path(str(spec_path), init_globals=globals_for_spec)
    return calls


def test_spec_is_parseable_onedir_and_includes_only_existing_optional_assets(tmp_path):
    spec_path = REPO_ROOT / "packaging" / "AudioTranscriber.spec"
    spec_text = spec_path.read_text(encoding="utf-8")
    ast.parse(spec_text)
    assert "COLLECT" in spec_text
    assert "onefile" not in spec_text.lower()
    assert 'name="AudioTranscriber"' in spec_text
    assert "console=False" in spec_text
    for module in (
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore",
        "pytest",
        "_pytest",
        "tests",
        "test",
    ):
        assert module in spec_text

    packaging_dir = tmp_path / "packaging"
    no_assets = _execute_spec(spec_text, packaging_dir)
    assert no_assets["analysis"]["datas"] == []
    assert no_assets["analysis"]["binaries"] == []
    assert no_assets["exe"]["console"] is False
    assert no_assets["exe"]["contents_directory"] == "."

    bin_dir = packaging_dir / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (bin_dir / "ffprobe.exe").write_bytes(b"ffprobe")
    (bin_dir / "avcodec-61.dll").write_bytes(b"codec")
    (bin_dir / "avutil-59.dll").write_bytes(b"util")
    licenses_dir = packaging_dir.parent / "LICENSES"
    licenses_dir.mkdir()
    populated = _execute_spec(spec_text, packaging_dir)["analysis"]
    destinations = {destination for _, destination in populated["datas"]}
    assert destinations == {"LICENSES"}
    binaries = {(Path(source).name, destination) for source, destination in populated["binaries"]}
    assert binaries == {
        ("ffmpeg.exe", "."),
        ("ffprobe.exe", "."),
        ("avcodec-61.dll", "."),
        ("avutil-59.dll", "."),
    }


def test_spec_collects_all_ffmpeg_shared_libraries(tmp_path):
    spec_path = REPO_ROOT / "packaging" / "AudioTranscriber.spec"
    spec_text = spec_path.read_text(encoding="utf-8")
    packaging_dir = tmp_path / "packaging"
    bin_dir = packaging_dir / "bin"
    bin_dir.mkdir(parents=True)
    expected_files = (
        "ffmpeg.exe",
        "ffprobe.exe",
        "avcodec-61.dll",
        "avformat-61.dll",
        "avfilter-10.dll",
        "avutil-59.dll",
        "swresample-5.dll",
    )
    for filename in expected_files:
        (bin_dir / filename).write_bytes(filename.encode())

    analysis = _execute_spec(spec_text, packaging_dir)["analysis"]

    binaries = {(Path(source).name, destination) for source, destination in analysis["binaries"]}
    assert binaries == {(filename, ".") for filename in expected_files}


def test_default_build_runner_uses_argv_and_reports_missing_pyinstaller(tmp_path, monkeypatch):
    calls = []

    def missing_pyinstaller(argv, *, cwd, check):
        calls.append((argv, cwd, check))
        raise FileNotFoundError("python environment has no PyInstaller")

    monkeypatch.setattr(build_release.subprocess, "run", missing_pyinstaller)

    with pytest.raises(RuntimeError, match="PyInstaller"):
        build_release.build(__version__, output_dir=tmp_path, repo_root=REPO_ROOT)

    argv, cwd, check = calls[0]
    assert isinstance(argv, list)
    assert "-m" in argv and "PyInstaller" in argv
    assert cwd == REPO_ROOT
    assert check is True


def test_build_cli_passes_version_repo_root_and_dist_directory(monkeypatch, tmp_path, capsys):
    archive = tmp_path / "AudioTranscriber-v1.2.3-win-x64.zip"
    calls = []

    def fake_build(version, *, output_dir, repo_root):
        calls.append((version, output_dir, repo_root))
        return archive

    monkeypatch.setattr(build_release, "build", fake_build)

    assert build_release.main(["--version", "1.2.3"]) == 0

    expected_root = REPO_ROOT.resolve()
    assert calls == [("1.2.3", expected_root / "dist", expected_root)]
    assert capsys.readouterr().out.strip() == str(archive)


def test_build_cli_returns_nonzero_and_reports_build_errors(monkeypatch, capsys):
    def failed_build(*args, **kwargs):
        raise RuntimeError("packaging failed")

    monkeypatch.setattr(build_release, "build", failed_build)

    assert build_release.main(["--version", "1.2.3"]) == 1
    assert "packaging failed" in capsys.readouterr().err


def test_build_cli_rejects_a_leading_v_before_calling_build(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(build_release, "build", lambda *args, **kwargs: calls.append(args))

    assert build_release.main(["--version", "v1.2.3"]) == 1

    assert calls == []
    assert "omit the leading 'v'" in capsys.readouterr().err


def test_build_script_cli_rejects_unsafe_version():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "packaging" / "build_release.py"),
            "--version",
            "../unsafe",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "version must contain only letters" in result.stderr


def test_build_refuses_to_create_zip_when_required_license_material_is_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        build_release,
        "collect_release_license_material",
        lambda destination, *, repo_root: None,
    )

    with pytest.raises(RuntimeError, match="license"):
        build_release.build(
            __version__, output_dir=tmp_path, repo_root=REPO_ROOT, runner=fake_pyinstaller_runner
        )

    assert not (tmp_path / "AudioTranscriber-v1.2.3-win-x64.zip").exists()
