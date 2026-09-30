"""Fetch the Windows FFmpeg tools used by the release bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from urllib.request import urlopen


FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)
_BINARY_NAMES = ("ffmpeg.exe", "ffprobe.exe")
LICENSE_FILENAME = "FFMPEG-LICENSE.txt"
ARCHIVE_METADATA_FILENAME = "FFMPEG-ARCHIVE-METADATA.txt"


def fetch(dest_dir: Path) -> tuple[Path, Path]:
    """Download and extract FFmpeg/FFprobe, unless both are already available.

    The upstream "latest" archive is not checksum-pinned in v1; callers should
    treat the downloaded binaries as unverified upstream artifacts. Its digest
    is recorded for traceability, not checked against a pinned value.
    """
    dest_dir = Path(dest_dir)
    destinations = tuple(dest_dir / name for name in _BINARY_NAMES)
    license_path = dest_dir / LICENSE_FILENAME
    metadata_path = dest_dir / ARCHIVE_METADATA_FILENAME
    required_assets = (*destinations, license_path, metadata_path)
    if all(path.is_file() and path.stat().st_size for path in required_assets):
        return destinations

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ffmpeg-download-", dir=dest_dir) as temp_name:
            temp_dir = Path(temp_name)
            archive_path = temp_dir / "ffmpeg.zip"
            with urlopen(FFMPEG_URL, timeout=120) as response, archive_path.open(
                "wb"
            ) as archive_file:
                shutil.copyfileobj(response, archive_file)

            with zipfile.ZipFile(archive_path) as archive:
                members: dict[str, zipfile.ZipInfo] = {}
                license_members: list[zipfile.ZipInfo] = []
                for member in archive.infolist():
                    parts = PurePosixPath(member.filename).parts
                    if member.is_dir():
                        continue
                    if len(parts) == 2 and parts[-1] == "LICENSE.txt":
                        license_members.append(member)
                    if len(parts) < 2 or parts[-2] != "bin":
                        continue
                    name = parts[-1]
                    if name in _BINARY_NAMES:
                        if name in members:
                            raise ValueError(f"archive contains more than one bin/{name}")
                        members[name] = member

                missing = sorted(set(_BINARY_NAMES) - members.keys())
                if missing:
                    raise ValueError(f"archive is missing required binaries: {', '.join(missing)}")
                if len(license_members) != 1:
                    raise ValueError(
                        "archive must contain exactly one top-level LICENSE.txt; "
                        f"found {len(license_members)}"
                    )

                staged = {}
                for name, member in members.items():
                    staged_path = temp_dir / name
                    with archive.open(member) as source, staged_path.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    staged[name] = staged_path
                license_info = license_members[0]
                license_staged = temp_dir / LICENSE_FILENAME
                with archive.open(license_info) as source, license_staged.open(
                    "wb"
                ) as destination:
                    shutil.copyfileobj(source, destination)
                if not license_staged.stat().st_size:
                    raise ValueError("archive LICENSE.txt is empty")

            archive_digest = hashlib.sha256()
            with archive_path.open("rb") as archive_file:
                for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
                    archive_digest.update(chunk)
            metadata_staged = temp_dir / ARCHIVE_METADATA_FILENAME
            metadata_staged.write_text(
                "FFmpeg/FFprobe build archive metadata\n"
                "=====================================\n"
                f"Source URL: {FFMPEG_URL}\n"
                f"Archive entry: {license_info.filename}\n"
                "Build variant: Windows x64 static GPL archive, as named by BtbN\n"
                f"Archive SHA-256 (traceability only; not pinned): "
                f"{archive_digest.hexdigest()}\n"
                "License text: FFMPEG-LICENSE.txt, copied from the archive's LICENSE.txt\n"
                "The source URL is the unpinned 'latest' release required by Task 12.\n",
                encoding="utf-8",
            )

            for name in _BINARY_NAMES:
                os.replace(staged[name], dest_dir / name)
            os.replace(license_staged, license_path)
            os.replace(metadata_staged, metadata_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch FFmpeg binaries from {FFMPEG_URL}: {exc}") from exc

    return destinations


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch FFmpeg binaries into the directory supplied on the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="directory in which to place ffmpeg.exe and ffprobe.exe")
    args = parser.parse_args(argv)

    try:
        if argv is None:
            fetch(Path(sys.argv[1]))
        else:
            fetch(Path(args.destination))
    except Exception as exc:
        print(f"Failed to fetch FFmpeg binaries: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
