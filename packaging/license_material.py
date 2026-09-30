"""Collect and validate third-party license material for the release bundle."""

from __future__ import annotations

import shutil
import sys
import hashlib
import re
import tarfile
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path, PurePosixPath
from urllib.request import urlopen

from packaging.markers import default_environment
from packaging.requirements import Requirement


class LicenseMaterialError(RuntimeError):
    """A required license text or notice could not be staged for release."""


REQUIRED_LICENSE_FILES = (
    "README.md",
    "THIRD-PARTY-NOTICES.md",
    "BUILD-METADATA.txt",
    "FFmpeg/LICENSE.txt",
    "FFmpeg/BUILD-METADATA.txt",
    "FFmpeg/SOURCE-OFFER.md",
    "FFmpeg/SOURCE-METADATA.txt",
    "FFmpeg/Source/ffmpeg-corresponding-source.tar.xz",
    "PySide6/LGPL-3.0-only.txt",
    "PySide6/Qt-GPL-exception-1.0.txt",
    "Qt/LGPL-3.0-only.txt",
    "httpx/LICENSE.md",
    "keyring/LICENSE",
    "Python/LICENSE.txt",
    "Python-Packages.md",
)

_SUBSTANTIVE_LICENSE_FILES = (
    "FFmpeg/LICENSE.txt",
    "PySide6/LGPL-3.0-only.txt",
    "PySide6/Qt-GPL-exception-1.0.txt",
    "Qt/LGPL-3.0-only.txt",
    "httpx/LICENSE.md",
    "keyring/LICENSE",
    "Python/LICENSE.txt",
)
_LICENSE_MINIMUM_BYTES = 512
_PACKAGING_ROOT_DISTRIBUTIONS = ("PySide6", "httpx", "keyring", "PyInstaller")
_FFMPEG_SOURCE_ARCHIVE = "ffmpeg-corresponding-source.tar.xz"

_LICENSE_BASENAMES = (
    "license",
    "copying",
    "notice",
    "copyright",
    "lgpl",
    "gpl",
    "qt-gpl-exception",
)


def validate_release_license_material(license_dir: Path) -> None:
    """Reject missing, empty, or insubstantial release license/source material."""
    license_dir = Path(license_dir)
    missing = [
        name
        for name in REQUIRED_LICENSE_FILES
        if not (license_dir / name).is_file() or not (license_dir / name).read_bytes().strip()
    ]
    if missing:
        joined = ", ".join(missing)
        raise LicenseMaterialError(
            "Required release license material is missing or empty: " + joined
        )
    insubstantial = [
        name
        for name in _SUBSTANTIVE_LICENSE_FILES
        if not _is_substantive_license((license_dir / name).read_bytes())
    ]
    if insubstantial:
        raise LicenseMaterialError(
            "Required release license text is not substantive or appears incomplete: "
            + ", ".join(insubstantial)
        )
    if not _is_substantive_license((license_dir / "FFmpeg/SOURCE-OFFER.md").read_bytes()):
        raise LicenseMaterialError("The FFmpeg source offer is missing or insubstantial")


def _distribution(name: str):
    try:
        return metadata.distribution(name)
    except metadata.PackageNotFoundError as exc:
        raise LicenseMaterialError(
            f"Required runtime distribution {name!r} is not installed; install the release dependencies"
        ) from exc


def _canonical_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _packaging_distributions() -> list:
    """Resolve direct app/build roots and their active transitive dependencies."""
    environment = default_environment()
    pending = list(_PACKAGING_ROOT_DISTRIBUTIONS)
    found = {}
    while pending:
        requested = pending.pop()
        normalized = _canonical_distribution_name(requested)
        if normalized in found:
            continue
        distribution = _distribution(requested)
        found[normalized] = distribution
        requirements = distribution.metadata.get_all("Requires-Dist")
        if requirements is None:
            requirements = getattr(distribution, "requires", None) or ()
        for raw_requirement in requirements:
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            pending.append(requirement.name)
    return sorted(
        found.values(),
        key=lambda item: _canonical_distribution_name(item.metadata.get("Name", "")),
    )


def _is_substantive_license(content: bytes) -> bool:
    text = content.decode("utf-8", errors="replace")
    folded = text.casefold()
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    if len(content.strip()) < _LICENSE_MINIMUM_BYTES or len(nonempty_lines) < 8:
        return False
    if any(marker in folded for marker in ("placeholder", "replace with license", "fixture license")):
        return False
    return True


def _collect_package_license_inventory(license_dir: Path) -> tuple[list[str], list[str]]:
    inventory_lines = [
        "# Packaging-environment license inventory",
        "",
        "This list is generated from the active dependency metadata for the app and PyInstaller.",
        "All listed distributions were present in the Windows release packaging environment.",
        "PyInstaller includes the PyInstaller bootloader binary; its wheel license material is included below.",
        "",
    ]
    provenance: list[str] = []
    for distribution in _packaging_distributions():
        package_name = distribution.metadata.get("Name", "unknown")
        version = distribution.version
        assets = _wheel_license_assets(distribution)
        if not any(_is_substantive_license(content) for _name, content in assets):
            raise LicenseMaterialError(
                f"Runtime/build distribution {package_name} {version} has no substantive full license text"
            )
        safe_name = _canonical_distribution_name(package_name)
        package_dir = license_dir / "Python-Packages" / safe_name
        copied = _copy_wheel_assets(distribution, package_dir)
        if not copied:
            raise LicenseMaterialError(
                f"Runtime/build distribution {package_name} {version} has no copyable license assets"
            )
        asset_paths = []
        for relative, content in copied:
            target = _wheel_asset_destination(
                package_dir, package_name, PurePosixPath(relative)
            )
            destination = target.relative_to(license_dir).as_posix()
            asset_paths.append(f"`{destination}`")
            provenance.append(f"{package_name} {version}: {relative}")
        note = " (contains the PyInstaller bootloader)" if safe_name == "pyinstaller" else ""
        inventory_lines.append(
            f"- **{package_name} {version}**{note}: " + ", ".join(asset_paths)
        )
    inventory_lines.append("")
    (license_dir / "Python-Packages.md").write_text(
        "\n".join(inventory_lines), encoding="utf-8"
    )
    return inventory_lines, provenance


def _is_license_asset(path: PurePosixPath, declared: set[str]) -> bool:
    path_text = path.as_posix()
    basename = path.name.casefold()
    return path_text in declared or any(
        basename == token
        or basename.startswith(f"{token}.")
        or basename.startswith(f"{token}-")
        or basename.startswith(f"{token}_")
        for token in _LICENSE_BASENAMES
    )


def _wheel_license_assets(distribution) -> list[tuple[PurePosixPath, bytes]]:
    declared = set(distribution.metadata.get_all("License-File") or [])
    assets: list[tuple[PurePosixPath, bytes]] = []
    for item in distribution.files or ():
        relative = PurePosixPath(str(item))
        if not _is_license_asset(relative, declared):
            continue
        source = Path(distribution.locate_file(item))
        if not source.is_file():
            continue
        content = source.read_bytes()
        if content.strip():
            assets.append((relative, content))
    return sorted(assets, key=lambda asset: asset[0].as_posix().casefold())


def _wheel_asset_destination(component_dir: Path, distribution_name: str, source: PurePosixPath):
    parts = source.parts
    dist_info_index = next(
        (index for index, part in enumerate(parts) if part.casefold().endswith(".dist-info")),
        None,
    )
    if dist_info_index is not None:
        relative_parts = parts[dist_info_index + 1 :]
        if relative_parts and relative_parts[0].casefold() == "licenses":
            relative_parts = relative_parts[1:]
    else:
        relative_parts = parts
    relative_parts = relative_parts or (source.name,)
    safe_name = distribution_name.casefold().replace("_", "-")
    base = component_dir / "wheel"
    if component_dir.name.casefold() != safe_name:
        base /= safe_name
    return base / Path(*relative_parts)


def _copy_wheel_assets(
    distribution,
    component_dir: Path,
) -> list[tuple[str, bytes]]:
    assets = _wheel_license_assets(distribution)
    for source, content in assets:
        target = _wheel_asset_destination(component_dir, distribution.metadata.get("Name", "package"), source)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return [(source.as_posix(), content) for source, content in assets]


def _find_asset(assets: Iterable[tuple[str, bytes]], predicate) -> tuple[str, bytes] | None:
    for name, content in assets:
        if predicate(name, content):
            return name, content
    return None


def _looks_like_lgpl_v3(name: str, content: bytes) -> bool:
    text = content.decode("utf-8", errors="replace").casefold()
    return "lesser general public license" in text and "version 3" in text[:1200]


def _looks_like_qt_gpl_exception(name: str, content: bytes) -> bool:
    text = content.decode("utf-8", errors="replace").casefold()
    return "exception" in text and "qt" in (name + text).casefold() and "gpl" in text


def _download_authoritative_license(url: str, description: str) -> bytes:
    try:
        with urlopen(url, timeout=30) as response:
            content = response.read()
    except Exception as exc:
        raise LicenseMaterialError(
            f"Could not obtain required {description} license text from {url}: {exc}"
        ) from exc
    if not _is_substantive_license(content):
        raise LicenseMaterialError(
            f"Upstream {description} license text is empty or insubstantial: {url}"
        )
    return content


def _copy_or_fetch_license(
    destination: Path,
    asset: tuple[str, bytes] | None,
    *,
    url: str,
    description: str,
) -> str:
    if asset is None:
        content = _download_authoritative_license(url, description)
        source = url
    else:
        source, content = asset
        if not _is_substantive_license(content):
            raise LicenseMaterialError(
                f"Installed {description} license text is not substantive or appears incomplete"
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return source


def _python_license() -> tuple[bytes, str]:
    candidates = (
        Path(sys.base_prefix) / "LICENSE.txt",
        Path(sys.base_prefix) / "LICENSE",
        Path(sys.prefix) / "LICENSE.txt",
        Path(sys.prefix) / "LICENSE",
    )
    for path in candidates:
        if path.is_file():
            content = path.read_bytes()
            if _is_substantive_license(content):
                return content, str(path)

    version = ".".join(str(part) for part in sys.version_info[:3])
    url = f"https://raw.githubusercontent.com/python/cpython/v{version}/LICENSE"
    return _download_authoritative_license(url, "Python PSF"), url


def _copy_required_wheel_license(distribution, destination: Path, label: str) -> str:
    assets = _wheel_license_assets(distribution)
    asset = _find_asset(
        assets,
        lambda name, content: (
            PurePosixPath(name).name.casefold().startswith("license")
            and _is_substantive_license(content)
        ),
    )
    if asset is None:
        raise LicenseMaterialError(
            f"Required {label} license file is missing from installed wheel metadata "
            f"({distribution.metadata.get('Name', label)} {distribution.version})"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(asset[1])
    return f"{distribution.metadata.get('Name', label)} {distribution.version}: {asset[0]}"


def _copy_ffmpeg_material(license_dir: Path, repo_root: Path) -> str:
    from fetch_ffmpeg import ARCHIVE_METADATA_FILENAME, LICENSE_FILENAME

    source_dir = Path(repo_root) / "packaging" / "bin"
    sources = (
        (source_dir / LICENSE_FILENAME, license_dir / "FFmpeg" / "LICENSE.txt"),
        (source_dir / ARCHIVE_METADATA_FILENAME, license_dir / "FFmpeg" / "BUILD-METADATA.txt"),
    )
    for source, destination in sources:
        if not source.is_file() or not source.read_bytes().strip():
            raise LicenseMaterialError(
                f"Required BtbN FFmpeg archive material is absent or empty: {source}; "
                "run packaging/fetch_ffmpeg.py to fetch the binaries and license text"
            )
        if source.name == LICENSE_FILENAME and not _is_substantive_license(source.read_bytes()):
            raise LicenseMaterialError(
                "The fetched FFmpeg LICENSE.txt is not a substantive full license text"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return f"BtbN archive: {sources[0][0]} and {sources[1][0]}"


def _copy_ffmpeg_source_material(license_dir: Path, repo_root: Path) -> tuple[str, str]:
    """Stage a hash-matched source archive and written offer or fail closed."""
    source_dir = Path(repo_root) / "packaging" / "ffmpeg-source-compliance"
    source_archive = source_dir / _FFMPEG_SOURCE_ARCHIVE
    source_metadata = source_dir / "SOURCE-METADATA.txt"
    source_offer = source_dir / "SOURCE-OFFER.md"
    required = (source_archive, source_metadata, source_offer)
    absent = [path.name for path in required if not path.is_file() or not path.stat().st_size]
    if absent:
        raise LicenseMaterialError(
            "Release blocker: exact corresponding FFmpeg source/offer is not established; "
            "missing " + ", ".join(absent) + ". Do not publish the release ZIP."
        )

    binary_metadata_path = Path(repo_root) / "packaging" / "bin" / "FFMPEG-ARCHIVE-METADATA.txt"
    try:
        binary_metadata = binary_metadata_path.read_text(encoding="utf-8")
        source_metadata_text = source_metadata.read_text(encoding="utf-8")
        offer_text = source_offer.read_text(encoding="utf-8")
        binary_hash = re.search(
            r"Archive SHA-256[^:]*:\s*([0-9a-f]{64})", binary_metadata, re.IGNORECASE
        ).group(1).lower()
        recorded_binary_hash = re.search(
            r"^Binary archive SHA-256:\s*([0-9a-f]{64})\s*$",
            source_metadata_text,
            re.IGNORECASE | re.MULTILINE,
        ).group(1).lower()
        recorded_source_hash = re.search(
            r"^Source archive SHA-256:\s*([0-9a-f]{64})\s*$",
            source_metadata_text,
            re.IGNORECASE | re.MULTILINE,
        ).group(1).lower()
        recorded_source_name = re.search(
            r"^Source archive:\s*(\S+)\s*$", source_metadata_text, re.MULTILINE
        ).group(1)
        verified_by = re.search(
            r"^Corresponding source verified by:\s*(.+?)\s*$",
            source_metadata_text,
            re.MULTILINE,
        ).group(1)
        verification_evidence = re.search(
            r"^Verification evidence:\s*(.+?)\s*$",
            source_metadata_text,
            re.MULTILINE,
        ).group(1)
    except (OSError, UnicodeError, AttributeError) as exc:
        raise LicenseMaterialError(
            "Release blocker: FFmpeg source metadata must identify the exact fetched binary "
            "archive and source archive hashes"
        ) from exc

    actual_source_hash = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    if (
        recorded_binary_hash != binary_hash
        or recorded_source_hash != actual_source_hash
        or recorded_source_name != source_archive.name
        or not verified_by.strip()
        or not verification_evidence.strip()
        or f"Binary archive SHA-256: {binary_hash}" not in offer_text
        or f"Source archive SHA-256: {actual_source_hash}" not in offer_text
        or _FFMPEG_SOURCE_ARCHIVE not in offer_text
        or not _is_substantive_license(source_offer.read_bytes())
    ):
        raise LicenseMaterialError(
            "Release blocker: FFmpeg source archive/offer does not match the exact fetched "
            "binary archive and verified source digest"
        )

    try:
        with tarfile.open(source_archive, mode="r:xz") as archive:
            names = [member.name.casefold() for member in archive.getmembers() if member.isfile()]
    except (OSError, tarfile.TarError) as exc:
        raise LicenseMaterialError(
            "Release blocker: corresponding FFmpeg source must be a readable .tar.xz source archive"
        ) from exc
    has_ffmpeg_source = any("ffmpeg" in name and name.endswith((".c", ".h", ".cpp")) for name in names)
    has_build_recipe = any(Path(name).name in {"configure", "build.sh", "build.ps1"} for name in names)
    if not has_ffmpeg_source or not has_build_recipe:
        raise LicenseMaterialError(
            "Release blocker: FFmpeg source archive lacks FFmpeg source files or the matching build recipe"
        )

    source_target = license_dir / "FFmpeg" / "Source"
    source_target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_archive, source_target / source_archive.name)
    shutil.copyfile(source_metadata, license_dir / "FFmpeg" / "SOURCE-METADATA.txt")
    shutil.copyfile(source_offer, license_dir / "FFmpeg" / "SOURCE-OFFER.md")
    return binary_hash, actual_source_hash


def collect_release_license_material(license_dir: Path, *, repo_root: Path) -> None:
    """Copy exact runtime license texts and archive provenance beside the application."""
    license_dir = Path(license_dir)
    license_dir.mkdir(parents=True, exist_ok=True)
    provenance: list[str] = []

    try:
        provenance.append(_copy_ffmpeg_material(license_dir, Path(repo_root)))
        ffmpeg_binary_hash, ffmpeg_source_hash = _copy_ffmpeg_source_material(
            license_dir, Path(repo_root)
        )
        provenance.append(
            f"FFmpeg source archive SHA-256: {ffmpeg_source_hash}; corresponding binary archive "
            f"SHA-256: {ffmpeg_binary_hash}"
        )

        _inventory, package_provenance = _collect_package_license_inventory(license_dir)
        provenance.extend(package_provenance)

        httpx = _distribution("httpx")
        keyring = _distribution("keyring")
        for distribution, component, filename in (
            (httpx, "httpx", "LICENSE.md"),
            (keyring, "keyring", "LICENSE"),
        ):
            component_dir = license_dir / component
            provenance.extend(
                f"{distribution.metadata.get('Name', component)} {distribution.version}: {path}"
                for path, _content in _copy_wheel_assets(distribution, component_dir)
            )
            provenance.append(
                _copy_required_wheel_license(
                    distribution, component_dir / filename, component
                )
            )

        pyside = _distribution("PySide6")
        shiboken = _distribution("shiboken6")
        qt_distributions = (
            _distribution("PySide6_Essentials"),
            _distribution("PySide6_Addons"),
        )
        for distribution in (shiboken, *qt_distributions):
            if distribution.version != pyside.version:
                raise LicenseMaterialError(
                    "PySide6, shiboken6, PySide6_Essentials, and PySide6_Addons must "
                    f"use one version; found PySide6 {pyside.version} and "
                    f"{distribution.metadata.get('Name', 'component')} {distribution.version}"
                )

        pyside_assets = _copy_wheel_assets(pyside, license_dir / "PySide6")
        shiboken_assets = _copy_wheel_assets(shiboken, license_dir / "PySide6")
        qt_assets: list[tuple[str, bytes]] = []
        for distribution, assets in (
            (pyside, pyside_assets),
            (shiboken, shiboken_assets),
        ):
            provenance.extend(
                f"{distribution.metadata.get('Name', 'PySide6')} {distribution.version}: {path}"
                for path, _content in assets
            )
        for distribution in qt_distributions:
            assets = _copy_wheel_assets(distribution, license_dir / "Qt")
            qt_assets.extend(assets)
            provenance.extend(
                f"{distribution.metadata.get('Name', 'Qt')} {distribution.version}: {path}"
                for path, _content in assets
            )

        pyside_lgpl = _find_asset(
            (*pyside_assets, *shiboken_assets), _looks_like_lgpl_v3
        )
        qt_lgpl = _find_asset(qt_assets, _looks_like_lgpl_v3)
        qt_exception = _find_asset(
            (*pyside_assets, *shiboken_assets, *qt_assets), _looks_like_qt_gpl_exception
        )
        pyside_url = (
            "https://raw.githubusercontent.com/pyside/pyside-setup/"
            f"{pyside.version}/LICENSES/LGPL-3.0-only.txt"
        )
        qt_url = (
            "https://raw.githubusercontent.com/qt/qtbase/"
            f"v{pyside.version}/LICENSES/LGPL-3.0-only.txt"
        )
        exception_url = (
            "https://raw.githubusercontent.com/pyside/pyside-setup/"
            f"{pyside.version}/LICENSES/Qt-GPL-exception-1.0.txt"
        )
        provenance.append(
            "PySide6 LGPLv3: "
            + _copy_or_fetch_license(
                license_dir / "PySide6" / "LGPL-3.0-only.txt",
                pyside_lgpl,
                url=pyside_url,
                description="PySide6 LGPLv3",
            )
        )
        provenance.append(
            "Qt LGPLv3: "
            + _copy_or_fetch_license(
                license_dir / "Qt" / "LGPL-3.0-only.txt",
                qt_lgpl,
                url=qt_url,
                description="Qt LGPLv3",
            )
        )
        provenance.append(
            "Qt GPL exception: "
            + _copy_or_fetch_license(
                license_dir / "PySide6" / "Qt-GPL-exception-1.0.txt",
                qt_exception,
                url=exception_url,
                description="Qt GPL exception",
            )
        )

        python_content, python_source = _python_license()
        python_target = license_dir / "Python" / "LICENSE.txt"
        python_target.parent.mkdir(parents=True, exist_ok=True)
        python_target.write_bytes(python_content)
        provenance.append(f"Python {'.'.join(map(str, sys.version_info[:3]))}: {python_source}")

        metadata_lines = [
            "Release license-material provenance",
            "====================================",
            "The required license files listed here were copied into this release bundle.",
            "This manifest records source files and runtime versions; it is not a legal opinion.",
            "",
            *sorted(set(provenance), key=str.casefold),
            "",
            "The FFmpeg URL is the Task 12 unpinned BtbN 'latest' archive. Its recorded",
            "SHA-256 identifies the fetched bytes for traceability only; it is not a pinned",
            "or verified checksum. The source bundle's operator-attested binary digest is",
            f"{ffmpeg_binary_hash}; the included source bundle digest is {ffmpeg_source_hash}.",
            "Review all additional notices required by the actual FFmpeg build before redistribution.",
            "",
        ]
        (license_dir / "BUILD-METADATA.txt").write_text(
            "\n".join(metadata_lines), encoding="utf-8"
        )
        validate_release_license_material(license_dir)
    except LicenseMaterialError:
        raise
    except Exception as exc:
        raise LicenseMaterialError(f"Could not collect release license material: {exc}") from exc
