from __future__ import annotations

import ast
import io
import runpy
import re
import shutil
import sys
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packaging"))

import build_release
import fetch_ffmpeg
from audio_transcriber import __version__


def _full_text(title: str) -> bytes:
    terms = "Permission is granted subject to the conditions and disclaimers below.\n"
    return (title + "\n\n" + terms * 24 + "\nAll rights reserved.\n").encode()

_RELEASE_LICENSES = {
    "BUILD-METADATA.txt": b"Collected package versions and provenance (fixture)\n",
    "FFmpeg/LICENSE.txt": _full_text("GNU GENERAL PUBLIC LICENSE Version 3"),
    "FFmpeg/BUILD-METADATA.txt": b"BtbN archive metadata (fixture)\n",
    "FFmpeg/SOURCE-OFFER.md": _full_text("Written corresponding FFmpeg source offer"),
    "FFmpeg/SOURCE-METADATA.txt": b"Binary/source archive digest metadata\n",
    "FFmpeg/Source/ffmpeg-corresponding-source.tar.xz": b"source archive fixture",
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
    (app_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (app_dir / "ffprobe.exe").write_bytes(b"ffprobe")

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
    assert "AudioTranscriber/LICENSES/FFmpeg/Source/ffmpeg-corresponding-source.tar.xz" in names
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
    for license_name in ("GPL v3", "LGPL v3", "BSD 3-Clause", "MIT", "PSF"):
        assert license_name in notices
    assert "Full license texts are not included" in notices


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
    assert no_assets["exe"]["console"] is False
    assert no_assets["exe"]["contents_directory"] == "."

    bin_dir = packaging_dir / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (bin_dir / "ffprobe.exe").write_bytes(b"ffprobe")
    licenses_dir = packaging_dir.parent / "LICENSES"
    licenses_dir.mkdir()
    datas = _execute_spec(spec_text, packaging_dir)["analysis"]["datas"]
    destinations = {destination for _, destination in datas}
    assert destinations == {".", "LICENSES"}


def _ffmpeg_archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe", b"ffmpeg-binary")
        archive.writestr("ffmpeg-master-latest-win64-gpl/bin/ffprobe.exe", b"ffprobe-binary")
        archive.writestr(
            "ffmpeg-master-latest-win64-gpl/LICENSE.txt",
            b"GNU GENERAL PUBLIC LICENSE Version 3 (BtbN archive fixture)\n",
        )
    return stream.getvalue()


def _write_cached_ffmpeg_assets(binary_dir: Path) -> tuple[Path, Path]:
    binary_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = binary_dir / "ffmpeg.exe"
    ffprobe = binary_dir / "ffprobe.exe"
    ffmpeg.write_bytes(b"existing ffmpeg")
    ffprobe.write_bytes(b"existing ffprobe")
    (binary_dir / fetch_ffmpeg.LICENSE_FILENAME).write_text(
        "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n",
        encoding="utf-8",
    )
    (binary_dir / fetch_ffmpeg.ARCHIVE_METADATA_FILENAME).write_text(
        f"Source URL: {fetch_ffmpeg.FFMPEG_URL}\n"
        "Archive entry: ffmpeg-master-latest-win64-gpl/LICENSE.txt\n"
        "Archive SHA-256 (traceability only; not pinned): " + "a" * 64 + "\n",
        encoding="utf-8",
    )
    return ffmpeg, ffprobe


def test_fetch_returns_existing_binaries_without_downloading(tmp_path, monkeypatch):
    binary_dir = tmp_path / "bin"
    ffmpeg, ffprobe = _write_cached_ffmpeg_assets(binary_dir)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("existing binaries should not trigger a download")

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", unexpected_download)
    assert fetch_ffmpeg.fetch(binary_dir) == (ffmpeg, ffprobe)


def test_fetch_cli_uses_license_complete_cache_without_network(tmp_path, monkeypatch):
    binary_dir = tmp_path / "ffmpeg bin"
    _write_cached_ffmpeg_assets(binary_dir)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("complete cached assets must not trigger a network fetch")

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", unexpected_download)

    assert fetch_ffmpeg.main([str(binary_dir)]) == 0


def test_fetch_downloads_binaries_and_license_material_from_archive(tmp_path, monkeypatch):
    archive_bytes = _ffmpeg_archive()
    monkeypatch.setattr(fetch_ffmpeg, "urlopen", lambda *args, **kwargs: io.BytesIO(archive_bytes))

    ffmpeg, ffprobe = fetch_ffmpeg.fetch(tmp_path / "bin")

    assert ffmpeg.read_bytes() == b"ffmpeg-binary"
    assert ffprobe.read_bytes() == b"ffprobe-binary"
    license_path = ffmpeg.parent / fetch_ffmpeg.LICENSE_FILENAME
    metadata_path = ffmpeg.parent / fetch_ffmpeg.ARCHIVE_METADATA_FILENAME
    assert license_path.read_bytes().startswith(b"GNU GENERAL PUBLIC LICENSE")
    assert b"BtbN archive fixture" in license_path.read_bytes()
    metadata = metadata_path.read_text(encoding="utf-8")
    assert fetch_ffmpeg.FFMPEG_URL in metadata
    assert "LICENSE.txt" in metadata
    assert re.search(r"Archive SHA-256 .*?: [0-9a-f]{64}", metadata)
    assert sorted(path.name for path in ffmpeg.parent.iterdir()) == sorted(
        [
            "ffmpeg.exe",
            "ffprobe.exe",
            fetch_ffmpeg.LICENSE_FILENAME,
            fetch_ffmpeg.ARCHIVE_METADATA_FILENAME,
        ]
    )


def test_fetch_fails_clearly_when_archive_has_no_license_text(tmp_path, monkeypatch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe", b"ffmpeg")
        archive.writestr("ffmpeg-master-latest-win64-gpl/bin/ffprobe.exe", b"ffprobe")
    monkeypatch.setattr(fetch_ffmpeg, "urlopen", lambda *args, **kwargs: io.BytesIO(stream.getvalue()))

    with pytest.raises(RuntimeError, match="LICENSE.txt"):
        fetch_ffmpeg.fetch(tmp_path / "bin")


def test_fetch_wraps_download_errors_with_the_source_url(tmp_path, monkeypatch):
    def failed_download(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(fetch_ffmpeg, "urlopen", failed_download)

    with pytest.raises(RuntimeError, match=fetch_ffmpeg.FFMPEG_URL):
        fetch_ffmpeg.fetch(tmp_path / "bin")


def test_fetch_cli_passes_the_destination_argument_as_a_path(monkeypatch, tmp_path):
    calls = []
    destination = tmp_path / "ffmpeg bin"
    monkeypatch.setattr(fetch_ffmpeg, "fetch", lambda path: calls.append(path))

    assert fetch_ffmpeg.main([str(destination)]) == 0

    assert calls == [destination]


def test_fetch_script_cli_accepts_destination_and_uses_existing_binaries(tmp_path):
    binary_dir = tmp_path / "ffmpeg bin"
    _write_cached_ffmpeg_assets(binary_dir)
    license_path = binary_dir / fetch_ffmpeg.LICENSE_FILENAME
    metadata_path = binary_dir / fetch_ffmpeg.ARCHIVE_METADATA_FILENAME
    assert license_path.is_file() and license_path.read_bytes().strip()
    assert metadata_path.is_file() and metadata_path.read_bytes().strip()

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "packaging" / "fetch_ffmpeg.py"), str(binary_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
