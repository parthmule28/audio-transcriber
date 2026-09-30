from __future__ import annotations

import shutil
import sys
import hashlib
import io
import tarfile
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packaging"))

import license_material


class FakeMetadata:
    def __init__(self, name: str, requirements: list[str] | None = None):
        self.values = {"Name": name}
        self.requirements = requirements or []

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def get_all(self, key: str):
        return self.requirements if key == "Requires-Dist" else []


class FakeDistribution:
    def __init__(self, name: str, version: str, root: Path, files: list[str], requires=None):
        self.metadata = FakeMetadata(name, requires)
        self.version = version
        self.root = root
        self.files = [PurePosixPath(path) for path in files]

    def locate_file(self, path):
        return self.root.joinpath(*PurePosixPath(str(path)).parts)


def _license_text(title: str) -> bytes:
    terms = "Permission is granted subject to the conditions and disclaimers below.\n"
    return (title + "\n\n" + terms * 24 + "\nAll rights reserved.\n").encode()


def _fake_environment(tmp_path: Path, *, qt_licenses: bool = True):
    roots = tmp_path / "site-packages"
    distributions = {}
    contents = {
        "httpx": ("httpx", "0.28.1", ["httpcore>=1", "certifi", "idna", "anyio"], {}),
        "keyring": (
            "keyring", "25.7.0",
            ["jaraco.classes", "jaraco.functools", "jaraco.context", "pywin32-ctypes; sys_platform == 'win32'"],
            {},
        ),
        "pyside6": (
            "PySide6", "6.11.2",
            ["PySide6_Essentials==6.11.2", "PySide6_Addons==6.11.2", "shiboken6==6.11.2"],
            {},
        ),
        "shiboken6": ("shiboken6", "6.11.2", [], {}),
        "pyside6-essentials": ("PySide6_Essentials", "6.11.2", ["shiboken6==6.11.2"], {}),
        "pyside6-addons": ("PySide6_Addons", "6.11.2", ["shiboken6==6.11.2"], {}),
        "pyinstaller": (
            "PyInstaller", "6.19.0",
            ["altgraph", "packaging", "pyinstaller-hooks-contrib", "pefile; sys_platform == 'win32'"],
            {},
        ),
        "httpcore": ("httpcore", "1.0.9", ["h11", "certifi", "anyio"], {}),
        "certifi": ("certifi", "2026.1", [], {}),
        "idna": ("idna", "3.10", [], {}),
        "anyio": ("anyio", "4.0", ["sniffio", "typing_extensions"], {}),
        "sniffio": ("sniffio", "1.3.1", [], {}),
        "typing-extensions": ("typing_extensions", "4.0", [], {}),
        "h11": ("h11", "0.16.0", [], {}),
        "jaraco.classes": ("jaraco.classes", "3.4.0", [], {}),
        "jaraco.functools": ("jaraco.functools", "4.0", [], {}),
        "jaraco.context": ("jaraco.context", "6.0", [], {}),
        "pywin32-ctypes": ("pywin32-ctypes", "0.2.3", [], {}),
        "altgraph": ("altgraph", "0.17.4", [], {}),
        "packaging": ("packaging", "26.3", [], {}),
        "pyinstaller-hooks-contrib": ("pyinstaller-hooks-contrib", "2026.1", [], {}),
        "pefile": ("pefile", "2024.8.26", [], {}),
    }
    if qt_licenses:
        contents["pyside6"][3].update(
            {
                "PySide6/LICENSES/LGPL-3.0-only.txt": _license_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3"),
                "PySide6/LICENSES/Qt-GPL-exception-1.0.txt": _license_text("Qt GPL exception text"),
            }
        )
        contents["pyside6-essentials"][3].update(
            {
                "PySide6/Qt/LICENSES/LGPL-3.0-only.txt": _license_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3"),
            }
        )

    for key, (name, version, requirements, files) in contents.items():
        if not any(
            PurePosixPath(path).name.casefold().startswith("license")
            for path in files
        ):
            files = {
                f"{key}-{version}.dist-info/licenses/LICENSE.txt": _license_text("MIT License"),
                **files,
            }
        root = roots / key
        for relative_path, content in files.items():
            path = root.joinpath(*PurePosixPath(relative_path).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        distributions[key] = FakeDistribution(
            name, version, root, list(files), requires=requirements
        )

    python_prefix = tmp_path / "python"
    python_prefix.mkdir()
    (python_prefix / "LICENSE.txt").write_bytes(_license_text("Python Software Foundation License"))
    repo_root = tmp_path / "repo"
    index_dir = repo_root / "LICENSES"
    index_dir.mkdir(parents=True)
    (index_dir / "README.md").write_text("License index\n", encoding="utf-8")
    (index_dir / "THIRD-PARTY-NOTICES.md").write_text("Notice index\n", encoding="utf-8")
    ffmpeg_dir = repo_root / "packaging" / "bin"
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "FFMPEG-LICENSE.txt").write_bytes(
        _license_text("GNU GENERAL PUBLIC LICENSE Version 3")
    )
    archive_hash = "a" * 64
    (ffmpeg_dir / "FFMPEG-ARCHIVE-METADATA.txt").write_text(
        "BtbN source URL and fetched archive SHA-256\n"
        f"Archive SHA-256 (traceability only; not pinned): {archive_hash}\n",
        encoding="utf-8",
    )
    source_dir = repo_root / "packaging" / "ffmpeg-source-compliance"
    source_dir.mkdir(parents=True)
    source_archive = source_dir / "ffmpeg-corresponding-source.tar.xz"
    with tarfile.open(source_archive, mode="w:xz") as archive:
        for name, content in (
            ("ffmpeg-source/configure", b"#!/bin/sh\n"),
            ("ffmpeg-source/libavcodec/ffmpeg_codec.c", b"int codec_fixture(void) { return 0; }\n"),
            ("ffmpeg-build/build.sh", b"#!/bin/sh\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    source_hash = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    (source_dir / "SOURCE-METADATA.txt").write_text(
        f"Binary archive SHA-256: {archive_hash}\n"
        f"Source archive SHA-256: {source_hash}\n"
        "Source archive: ffmpeg-corresponding-source.tar.xz\n"
        "Corresponding source verified by: test fixture maintainer\n"
        "Verification evidence: test fixture source and build-script manifest\n",
        encoding="utf-8",
    )
    (source_dir / "SOURCE-OFFER.md").write_bytes(_license_text(
        f"Written offer for the exact corresponding FFmpeg source archive.\n"
        f"Binary archive SHA-256: {archive_hash}\n"
        f"Source archive SHA-256: {source_hash}\n"
        "The matching ffmpeg-corresponding-source.tar.xz is included with the release."
    ))
    return distributions, python_prefix, repo_root


def _patch_environment(monkeypatch, distributions, python_prefix):
    def distribution(name):
        key = name.casefold().replace("_", "-")
        return distributions[key]

    monkeypatch.setattr(license_material.metadata, "distribution", distribution)
    monkeypatch.setattr(license_material.sys, "base_prefix", str(python_prefix))
    monkeypatch.setattr(license_material.sys, "prefix", str(python_prefix))
    from packaging.markers import default_environment

    environment = default_environment()
    environment["sys_platform"] = "win32"
    monkeypatch.setattr(
        license_material, "default_environment", lambda: environment, raising=False
    )


def _stage_index(destination: Path, repo_root: Path):
    destination.mkdir(parents=True)
    shutil.copyfile(repo_root / "LICENSES" / "README.md", destination / "README.md")
    shutil.copyfile(
        repo_root / "LICENSES" / "THIRD-PARTY-NOTICES.md",
        destination / "THIRD-PARTY-NOTICES.md",
    )


def test_collects_nonempty_wheel_archive_and_runtime_license_material(tmp_path, monkeypatch):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path)
    _patch_environment(monkeypatch, distributions, python_prefix)

    def unexpected_download(*args, **kwargs):
        raise AssertionError("available wheel and runtime licenses should be reused")

    monkeypatch.setattr(license_material, "urlopen", unexpected_download)
    destination = tmp_path / "release" / "LICENSES"
    _stage_index(destination, repo_root)

    license_material.collect_release_license_material(destination, repo_root=repo_root)

    expected = (
        "FFmpeg/LICENSE.txt",
        "PySide6/LGPL-3.0-only.txt",
        "PySide6/Qt-GPL-exception-1.0.txt",
        "Qt/LGPL-3.0-only.txt",
        "httpx/LICENSE.md",
        "keyring/LICENSE",
        "Python/LICENSE.txt",
    )
    for relative_path in expected:
        path = destination / relative_path
        assert path.is_file()
        assert path.stat().st_size > 512
    assert (destination / "FFmpeg/BUILD-METADATA.txt").is_file()
    assert (destination / "keyring/wheel/LICENSE.txt").stat().st_size > 512
    assert (destination / "httpx/wheel/LICENSE.txt").stat().st_size > 512
    metadata = (destination / "BUILD-METADATA.txt").read_text(encoding="utf-8")
    assert "PySide6 6.11.2:" in metadata
    assert "PySide6_Essentials 6.11.2:" in metadata
    assert "BtbN 'latest' archive" in metadata
    assert (destination / "FFmpeg/Source/ffmpeg-corresponding-source.tar.xz").is_file()
    license_material.validate_release_license_material(destination)


def test_uses_version_pinned_authoritative_qt_and_pyside_sources_when_wheels_omit_texts(
    tmp_path, monkeypatch
):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path, qt_licenses=False)
    _patch_environment(monkeypatch, distributions, python_prefix)
    (python_prefix / "LICENSE.txt").unlink()
    python_version = ".".join(str(part) for part in sys.version_info[:3])
    python_url = f"https://raw.githubusercontent.com/python/cpython/v{python_version}/LICENSE"
    license_texts = {
        "https://raw.githubusercontent.com/pyside/pyside-setup/6.11.2/LICENSES/LGPL-3.0-only.txt": _license_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3 Pinned PySide source"),
        "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/LGPL-3.0-only.txt": _license_text("GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3 Pinned Qt source"),
        "https://raw.githubusercontent.com/pyside/pyside-setup/6.11.2/LICENSES/Qt-GPL-exception-1.0.txt": _license_text("Qt GPL exception pinned source"),
        python_url: _license_text("Python Software Foundation License pinned CPython source"),
    }
    requested = []

    def download(url, *, timeout):
        requested.append(url)
        from io import BytesIO

        return BytesIO(license_texts[url])

    monkeypatch.setattr(license_material, "urlopen", download)
    destination = tmp_path / "release" / "LICENSES"
    _stage_index(destination, repo_root)

    license_material.collect_release_license_material(destination, repo_root=repo_root)

    assert requested == list(license_texts)
    assert (destination / "PySide6/LGPL-3.0-only.txt").read_bytes() == license_texts[requested[0]]
    assert (destination / "Qt/LGPL-3.0-only.txt").read_bytes() == license_texts[requested[1]]
    assert (destination / "PySide6/Qt-GPL-exception-1.0.txt").read_bytes() == license_texts[
        requested[2]
    ]
    assert (destination / "Python/LICENSE.txt").read_bytes() == license_texts[python_url]


def test_collection_fails_when_bbtn_archive_material_is_missing(tmp_path, monkeypatch):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path)
    _patch_environment(monkeypatch, distributions, python_prefix)
    (repo_root / "packaging" / "bin" / "FFMPEG-LICENSE.txt").unlink()

    with pytest.raises(license_material.LicenseMaterialError, match="BtbN FFmpeg archive material"):
        license_material.collect_release_license_material(
            tmp_path / "release" / "LICENSES", repo_root=repo_root
        )


def test_license_inventory_includes_transitive_runtime_and_pyinstaller_bootloader(
    tmp_path, monkeypatch
):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path)
    _patch_environment(monkeypatch, distributions, python_prefix)
    destination = tmp_path / "release" / "LICENSES"
    _stage_index(destination, repo_root)

    license_material.collect_release_license_material(destination, repo_root=repo_root)

    inventory = (destination / "Python-Packages.md").read_text(encoding="utf-8")
    for package in (
        "PySide6_Essentials", "PySide6_Addons", "httpcore", "certifi", "anyio",
        "jaraco.classes", "pywin32-ctypes", "PyInstaller", "altgraph", "pefile",
        "pyinstaller-hooks-contrib",
    ):
        assert package in inventory
    assert "bootloader" in inventory.lower()
    package_texts = [
        path
        for path in (destination / "Python-Packages").rglob("LICENSE*")
        if path.is_file()
    ]
    assert package_texts
    assert all(path.stat().st_size > 512 for path in package_texts)


def test_collection_fails_when_a_transitive_package_license_is_missing(tmp_path, monkeypatch):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path)
    certifi = distributions["certifi"]
    certifi_license = certifi.locate_file(certifi.files[0])
    certifi_license.unlink()
    _patch_environment(monkeypatch, distributions, python_prefix)
    destination = tmp_path / "release" / "LICENSES"
    _stage_index(destination, repo_root)

    with pytest.raises(license_material.LicenseMaterialError, match="certifi"):
        license_material.collect_release_license_material(
            destination, repo_root=repo_root
        )


def test_collection_rejects_short_placeholder_package_license(tmp_path, monkeypatch):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path)
    httpcore = distributions["httpcore"]
    httpcore_license = httpcore.locate_file(httpcore.files[0])
    httpcore_license.write_text("placeholder license text", encoding="utf-8")
    _patch_environment(monkeypatch, distributions, python_prefix)
    destination = tmp_path / "release" / "LICENSES"
    _stage_index(destination, repo_root)

    with pytest.raises(license_material.LicenseMaterialError, match="httpcore"):
        license_material.collect_release_license_material(
            destination, repo_root=repo_root
        )


def test_collection_fails_closed_if_exact_ffmpeg_source_bundle_is_absent(tmp_path, monkeypatch):
    distributions, python_prefix, repo_root = _fake_environment(tmp_path)
    _patch_environment(monkeypatch, distributions, python_prefix)
    (repo_root / "packaging" / "ffmpeg-source-compliance" / "ffmpeg-corresponding-source.tar.xz").unlink()
    destination = tmp_path / "release" / "LICENSES"
    _stage_index(destination, repo_root)

    with pytest.raises(license_material.LicenseMaterialError, match="corresponding FFmpeg source"):
        license_material.collect_release_license_material(
            destination, repo_root=repo_root
        )
