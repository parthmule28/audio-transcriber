"""Build and archive the Windows onedir application distribution."""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable, Sequence
from pathlib import Path

from license_material import collect_release_license_material, validate_release_license_material


_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*\Z")
_EXCLUDED_AUDIO_SUFFIXES = {".wav", ".m4a", ".mp3"}


def _package_version(repo_root: Path) -> str:
    """Read the single package version source without importing application code."""
    init_path = repo_root / "src" / "audio_transcriber" / "__init__.py"
    module = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError("src/audio_transcriber/__init__.py must define a literal __version__")


def _default_runner(argv: Sequence[str], *, cwd: Path) -> None:
    subprocess.run(list(argv), cwd=cwd, check=True)


def _is_excluded(relative_path: Path) -> bool:
    is_license_material = (
        bool(relative_path.parts) and relative_path.parts[0].casefold() == "licenses"
    )
    for part in relative_path.parts:
        folded = part.casefold()
        if "key" in folded and not (is_license_material and folded == "keyring"):
            return True
        if folded == ".env" or folded.startswith(".env."):
            return True
        if Path(part).suffix.casefold() in _EXCLUDED_AUDIO_SUFFIXES:
            return True
    return False


def _add_distribution(zip_file: zipfile.ZipFile, distribution: Path) -> None:
    zip_file.writestr("AudioTranscriber/", "")
    for path in sorted(distribution.rglob("*")):
        relative_path = path.relative_to(distribution)
        if _is_excluded(relative_path) or path.is_symlink():
            continue

        archive_name = (Path("AudioTranscriber") / relative_path).as_posix()
        if path.is_dir():
            zip_file.writestr(f"{archive_name}/", "")
        elif path.is_file():
            zip_file.write(path, archive_name)


def build(
    version: str,
    *,
    output_dir: Path,
    repo_root: Path,
    runner: Callable[..., object] | None = None,
) -> Path:
    """Run PyInstaller and return the versioned onedir release ZIP path."""
    if not isinstance(version, str) or not _VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must contain only letters, digits, '.', '+', or '-' and start alphanumeric")

    repo_root = Path(repo_root).resolve()
    output_dir = Path(output_dir).resolve()
    package_version = _package_version(repo_root)
    if version != package_version:
        raise ValueError(
            f"release version {version!r} must match package version {package_version!r}"
        )
    spec_path = repo_root / "packaging" / "AudioTranscriber.spec"
    if not spec_path.is_file():
        raise FileNotFoundError(f"PyInstaller spec does not exist: {spec_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"AudioTranscriber-v{version}-win-x64.zip"
    run_pyinstaller = runner if runner is not None else _default_runner

    with tempfile.TemporaryDirectory(prefix=".audiotranscriber-build-", dir=output_dir) as temp_name:
        work_dir = Path(temp_name)
        dist_dir = work_dir / "dist"
        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir / "work"),
            str(spec_path),
        ]
        try:
            run_pyinstaller(command, cwd=repo_root)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError(
                "PyInstaller is unavailable or failed; install the packaging dependencies and retry"
            ) from exc

        distribution = dist_dir / "AudioTranscriber"
        if not distribution.is_dir():
            raise RuntimeError(f"PyInstaller did not produce the onedir distribution: {distribution}")
        if not (distribution / "AudioTranscriber.exe").is_file():
            raise RuntimeError(f"PyInstaller output is missing AudioTranscriber.exe: {distribution}")

        license_dir = distribution / "LICENSES"
        collect_release_license_material(license_dir, repo_root=repo_root)
        validate_release_license_material(license_dir)

        temp_archive = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{archive_path.name}.", suffix=".tmp", dir=output_dir, delete=False
            ) as temp_file:
                temp_archive = Path(temp_file.name)
            with zipfile.ZipFile(temp_archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
                _add_distribution(zip_file, distribution)
            os.replace(temp_archive, archive_path)
        finally:
            if temp_archive is not None:
                temp_archive.unlink(missing_ok=True)

    return archive_path


def zip_contents(zip_path: Path) -> list[str]:
    """Return archive member names sorted for stable tests and inspection."""
    with zipfile.ZipFile(zip_path) as archive:
        return sorted(archive.namelist())


def main(argv: Sequence[str] | None = None) -> int:
    """Build the release ZIP using argv-safe command-line parsing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        required=True,
        help="release version without the leading 'v' (for example, 0.1.0)",
    )
    args = parser.parse_args(argv)
    if args.version[:1].casefold() == "v":
        print("Failed to build release: omit the leading 'v' from the version", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parents[1]

    try:
        archive = build(args.version, output_dir=repo_root / "dist", repo_root=repo_root)
    except Exception as exc:
        print(f"Failed to build release: {exc}", file=sys.stderr)
        return 1

    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
