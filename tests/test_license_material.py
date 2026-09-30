from __future__ import annotations

import shutil
import sys
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packaging"))

import license_material


class FakeMetadata:
    def __init__(self, name: str, license_files: list[str] | None = None):
        self.values = {"Name": name}
        self.license_files = license_files or []

    def get(self, key: str, default=None):
        return self.values.get(key, default)

    def get_all(self, key: str):
        return self.license_files if key == "License-File" else []


class FakeDistribution:
    def __init__(self, name: str, version: str, root: Path, files: list[str]):
        self.metadata = FakeMetadata(name)
        self.version = version
        self.root = root
        self.files = [PurePosixPath(path) for path in files]

    def locate_file(self, path):
        return self.root.joinpath(*PurePosixPath(str(path)).parts)


def _fake_environment(tmp_path: Path, *, qt_licenses: bool = True):
    roots = tmp_path / "site-packages"
    distributions = {}
    contents = {
        "httpx": (
            "httpx",
            "0.28.1",
            {"httpx-0.28.1.dist-info/licenses/LICENSE.md": b"BSD 3-Clause License\n"},
        ),
        "keyring": (
            "keyring",
            "25.7.0",
            {"keyring-25.7.0.dist-info/licenses/LICENSE": b"MIT License\n"},
        ),
        "pyside6": ("PySide6", "6.11.2", {}),
        "shiboken6": ("shiboken6", "6.11.2", {}),
        "pyside6-essentials": ("PySide6_Essentials", "6.11.2", {}),
        "pyside6-addons": ("PySide6_Addons", "6.11.2", {}),
    }
    if qt_licenses:
        contents["pyside6"][2].update(
            {
                "PySide6/LICENSES/LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\nPySide wheel source\n",
                "PySide6/LICENSES/Qt-GPL-exception-1.0.txt": b"Qt GPL exception text\n",
            }
        )
        contents["pyside6-essentials"][2].update(
            {
                "PySide6/Qt/LICENSES/LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\nQt wheel source\n",
            }
        )

    for key, (name, version, files) in contents.items():
        root = roots / key
        for relative_path, content in files.items():
            path = root.joinpath(*PurePosixPath(relative_path).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        distributions[key] = FakeDistribution(name, version, root, list(files))

    python_prefix = tmp_path / "python"
    python_prefix.mkdir()
    (python_prefix / "LICENSE.txt").write_bytes(b"Python Software Foundation License\n")
    repo_root = tmp_path / "repo"
    index_dir = repo_root / "LICENSES"
    index_dir.mkdir(parents=True)
    (index_dir / "README.md").write_text("License index\n", encoding="utf-8")
    (index_dir / "THIRD-PARTY-NOTICES.md").write_text("Notice index\n", encoding="utf-8")
    ffmpeg_dir = repo_root / "packaging" / "bin"
    ffmpeg_dir.mkdir(parents=True)
    (ffmpeg_dir / "FFMPEG-LICENSE.txt").write_bytes(b"GNU GENERAL PUBLIC LICENSE Version 3\n")
    (ffmpeg_dir / "FFMPEG-ARCHIVE-METADATA.txt").write_bytes(
        b"BtbN source URL and fetched archive SHA-256\n"
    )
    return distributions, python_prefix, repo_root


def _patch_environment(monkeypatch, distributions, python_prefix):
    def distribution(name):
        key = name.casefold().replace("_", "-")
        return distributions[key]

    monkeypatch.setattr(license_material.metadata, "distribution", distribution)
    monkeypatch.setattr(license_material.sys, "base_prefix", str(python_prefix))
    monkeypatch.setattr(license_material.sys, "prefix", str(python_prefix))


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

    expected = {
        "FFmpeg/LICENSE.txt": b"GNU GENERAL PUBLIC LICENSE Version 3\n",
        "FFmpeg/BUILD-METADATA.txt": b"BtbN source URL and fetched archive SHA-256\n",
        "PySide6/LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\nPySide wheel source\n",
        "PySide6/Qt-GPL-exception-1.0.txt": b"Qt GPL exception text\n",
        "Qt/LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\nQt wheel source\n",
        "httpx/LICENSE.md": b"BSD 3-Clause License\n",
        "keyring/LICENSE": b"MIT License\n",
        "Python/LICENSE.txt": b"Python Software Foundation License\n",
    }
    for relative_path, content in expected.items():
        path = destination / relative_path
        assert path.is_file()
        assert path.read_bytes() == content
        assert path.stat().st_size > 0
    assert (destination / "keyring/wheel/LICENSE").read_bytes() == b"MIT License\n"
    assert (destination / "httpx/wheel/LICENSE.md").read_bytes() == b"BSD 3-Clause License\n"
    metadata = (destination / "BUILD-METADATA.txt").read_text(encoding="utf-8")
    assert "PySide6 6.11.2:" in metadata
    assert "PySide6_Essentials 6.11.2:" in metadata
    assert "BtbN 'latest' archive" in metadata
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
        "https://raw.githubusercontent.com/pyside/pyside-setup/6.11.2/LICENSES/LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\nPinned PySide source\n",
        "https://raw.githubusercontent.com/qt/qtbase/v6.11.2/LICENSES/LGPL-3.0-only.txt": b"GNU LESSER GENERAL PUBLIC LICENSE\nVersion 3\nPinned Qt source\n",
        "https://raw.githubusercontent.com/pyside/pyside-setup/6.11.2/LICENSES/Qt-GPL-exception-1.0.txt": b"Qt GPL exception (pinned source)\n",
        python_url: b"Python Software Foundation License (pinned CPython source)\n",
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
