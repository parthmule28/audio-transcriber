"""Fetch and pin the official FFmpeg source archive and detached signature."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from urllib.request import urlopen


FFMPEG_VERSION = "9.0.2"
SOURCE_ARCHIVE_NAME = f"ffmpeg-{FFMPEG_VERSION}.tar.xz"
SOURCE_URL = f"https://ffmpeg.org/releases/{SOURCE_ARCHIVE_NAME}"
SOURCE_SIGNATURE_NAME = SOURCE_ARCHIVE_NAME + ".asc"
SIGNATURE_URL = SOURCE_URL + ".asc"
SOURCE_SHA256 = "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"
RELEASE_KEY_FINGERPRINT = "FCF986EA15E6E293A5644F10B4322F04D67658D8"
DOWNLOAD_TIMEOUT_SECONDS = 120


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str, destination: Path, *, opener: Callable | None = None
) -> None:
    if opener is None:
        opener = urlopen
    with opener(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out)


def fetch(dest_dir: Path) -> tuple[Path, Path]:
    """Download the pinned source and signature, rejecting incomplete or altered caches."""
    dest_dir = Path(dest_dir)
    source_path = dest_dir / SOURCE_ARCHIVE_NAME
    signature_path = dest_dir / SOURCE_SIGNATURE_NAME

    if source_path.exists():
        if not source_path.is_file() or _sha256(source_path) != SOURCE_SHA256:
            raise RuntimeError(f"Cached FFmpeg source archive failed SHA-256 validation: {source_path}")
        if not signature_path.is_file() or not signature_path.stat().st_size:
            raise RuntimeError(f"Cached FFmpeg source signature is missing or empty: {signature_path}")
        return source_path, signature_path

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ffmpeg-source-", dir=dest_dir) as temp_name:
            temp_dir = Path(temp_name)
            staged_source = temp_dir / SOURCE_ARCHIVE_NAME
            staged_signature = temp_dir / SOURCE_SIGNATURE_NAME
            _download(SOURCE_URL, staged_source)
            actual_digest = _sha256(staged_source)
            if actual_digest != SOURCE_SHA256:
                raise ValueError(
                    f"FFmpeg source SHA-256 mismatch: expected {SOURCE_SHA256}, got {actual_digest}"
                )
            _download(SIGNATURE_URL, staged_signature)
            if not staged_signature.stat().st_size:
                raise ValueError("FFmpeg detached source signature is empty")

            # Publish the signature first; the source archive is the cache marker and is
            # replaced last, so an interrupted staging operation is never a cache hit.
            os.replace(staged_signature, signature_path)
            os.replace(staged_source, source_path)
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch pinned FFmpeg source from {SOURCE_URL}: {exc}") from exc

    return source_path, signature_path


def main(argv: Sequence[str] | None = None) -> int:
    """Fetch the pinned FFmpeg source inputs into the destination directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="directory in which to place the pinned source archive")
    args = parser.parse_args(argv)

    try:
        fetch(Path(args.destination))
    except Exception as exc:
        print(f"Failed to fetch FFmpeg source: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
