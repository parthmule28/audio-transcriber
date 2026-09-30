"""Fetch the Windows FFmpeg tools used by the release bundle."""

from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.request import urlopen


FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
_BINARY_NAMES = ("ffmpeg.exe", "ffprobe.exe")


def fetch(dest_dir: Path) -> tuple[Path, Path]:
    """Download and extract FFmpeg/FFprobe, unless both are already available.

    The upstream "latest" archive is not checksum-pinned in v1; callers should
    treat the downloaded binaries as unverified upstream artifacts.
    """
    dest_dir = Path(dest_dir)
    destinations = tuple(dest_dir / name for name in _BINARY_NAMES)
    if all(path.is_file() for path in destinations):
        return destinations

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ffmpeg-download-", dir=dest_dir) as temp_name:
            temp_dir = Path(temp_name)
            archive_path = temp_dir / "ffmpeg.zip"
            with urlopen(FFMPEG_URL, timeout=120) as response, archive_path.open("wb") as archive_file:
                shutil.copyfileobj(response, archive_file)

            with zipfile.ZipFile(archive_path) as archive:
                members: dict[str, zipfile.ZipInfo] = {}
                for member in archive.infolist():
                    parts = PurePosixPath(member.filename).parts
                    if member.is_dir() or len(parts) < 2 or parts[-2] != "bin":
                        continue
                    name = parts[-1]
                    if name in _BINARY_NAMES:
                        if name in members:
                            raise ValueError(f"archive contains more than one bin/{name}")
                        members[name] = member

                missing = sorted(set(_BINARY_NAMES) - members.keys())
                if missing:
                    raise ValueError(f"archive is missing required binaries: {', '.join(missing)}")

                staged = {}
                for name, member in members.items():
                    staged_path = temp_dir / name
                    with archive.open(member) as source, staged_path.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    staged[name] = staged_path

            for name in _BINARY_NAMES:
                os.replace(staged[name], dest_dir / name)
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch FFmpeg binaries from {FFMPEG_URL}: {exc}") from exc

    return destinations
