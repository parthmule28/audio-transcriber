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
from fetch_ffmpeg import (
    FFMPEG_VERSION,
    RELEASE_KEY_FINGERPRINT,
    SOURCE_ARCHIVE_NAME,
    SOURCE_SHA256,
    SOURCE_URL,
)


class LicenseMaterialError(RuntimeError):
    """A required license text or notice could not be staged for release."""


REQUIRED_LICENSE_FILES = (
    "README.md",
    "THIRD-PARTY-NOTICES.md",
    "BUILD-METADATA.txt",
    "FFmpeg/LICENSE-LGPL-2.1.txt",
    "FFmpeg/BUILD-METADATA.txt",
    "FFmpeg/SOURCE-OFFER.md",
    f"FFmpeg/Source/{SOURCE_ARCHIVE_NAME}",
    f"FFmpeg/Source/{SOURCE_ARCHIVE_NAME}.asc",
    "FFmpeg/Source/ffmpeg-release-key.asc",
    "FFmpeg/Source/build_ffmpeg.sh",
    "FFmpeg/Source/fetch_ffmpeg.py",
    "PySide6/LGPL-3.0-only.txt",
    "PySide6/Qt-GPL-exception-1.0.txt",
    "Qt/LGPL-3.0-only.txt",
    "httpx/LICENSE.md",
    "keyring/LICENSE",
    "Python/LICENSE.txt",
    "Python-Packages.md",
)

_SUBSTANTIVE_LICENSE_FILES = (
    "FFmpeg/LICENSE-LGPL-2.1.txt",
    "PySide6/LGPL-3.0-only.txt",
    "PySide6/Qt-GPL-exception-1.0.txt",
    "Qt/LGPL-3.0-only.txt",
    "httpx/LICENSE.md",
    "keyring/LICENSE",
    "Python/LICENSE.txt",
)
_LICENSE_MINIMUM_BYTES = 512
_PACKAGING_ROOT_DISTRIBUTIONS = ("PySide6", "httpx", "keyring", "PyInstaller")
FFMPEG_SOURCE_SHA256 = SOURCE_SHA256
_FFMPEG_RUNTIME_EXECUTABLES = ("ffmpeg.exe", "ffprobe.exe")
_FFMPEG_METADATA_FILE = "FFMPEG-BUILD-METADATA.txt"

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
    _validate_ffmpeg_release_bundle(license_dir)


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


def _metadata_value(metadata_text: str, label: str) -> str:
    matches = re.findall(
        rf"^{re.escape(label)}:\s*(.*?)\s*$", metadata_text, re.MULTILINE
    )
    if len(matches) != 1 or not matches[0]:
        raise LicenseMaterialError(f"FFmpeg build metadata must contain one {label!r} field")
    return matches[0]


def _runtime_hashes(metadata_text: str) -> dict[str, str]:
    if "Runtime-file SHA-256:" not in metadata_text:
        raise LicenseMaterialError("FFmpeg build metadata is missing runtime SHA-256 records")
    hashes: dict[str, str] = {}
    for digest, name in re.findall(
        r"^([0-9a-f]{64})\s{2,}(.+?)\s*$", metadata_text, re.MULTILINE
    ):
        safe_name = Path(name.removeprefix("./")).name
        if safe_name in hashes:
            raise LicenseMaterialError(f"Duplicate FFmpeg runtime SHA-256 record for {safe_name}")
        hashes[safe_name] = digest
    required = set(_FFMPEG_RUNTIME_EXECUTABLES)
    if not required.issubset(hashes) or not any(name.lower().endswith(".dll") for name in hashes):
        raise LicenseMaterialError(
            "FFmpeg build metadata must hash ffmpeg.exe, ffprobe.exe, and every shared DLL"
        )
    return hashes


def _validate_ffmpeg_source_archive(source_archive: Path) -> None:
    try:
        with tarfile.open(source_archive, mode="r:xz") as archive:
            names = [
                member.name.casefold()
                for member in archive.getmembers()
                if member.isfile()
            ]
    except (OSError, tarfile.TarError) as exc:
        raise LicenseMaterialError(
            "The pinned FFmpeg corresponding source must be a readable .tar.xz archive"
        ) from exc
    if not any(Path(name).name == "configure" for name in names):
        raise LicenseMaterialError("The FFmpeg source archive is missing its configure script")
    if not any(Path(name).name == "copying.lgplv2.1" for name in names):
        raise LicenseMaterialError("The FFmpeg source archive is missing COPYING.LGPLv2.1")
    if not any(
        name.endswith((".c", ".h", ".cpp"))
        and any(part.startswith("libav") for part in Path(name).parts)
        for name in names
    ):
        raise LicenseMaterialError("The FFmpeg source archive contains no libav source files")


def _verify_runtime_hashes(metadata_text: str, runtime_dir: Path, *, staged: bool) -> None:
    recorded = _runtime_hashes(metadata_text)
    runtime_dir = Path(runtime_dir)
    for name, expected in recorded.items():
        path = runtime_dir / name
        if not path.is_file() or not path.stat().st_size:
            raise LicenseMaterialError(f"FFmpeg runtime file is missing or empty: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise LicenseMaterialError(
                f"FFmpeg runtime SHA-256 mismatch for {name}: expected {expected}, got {actual}"
            )

    recorded_dlls = {name for name in recorded if name.lower().endswith(".dll")}
    if staged:
        actual_dlls = {path.name for path in runtime_dir.glob("*.dll") if path.is_file()}
    else:
        actual_dlls = {
            path.name
            for pattern in ("libav*.dll", "libsw*.dll")
            for path in runtime_dir.glob(pattern)
            if path.is_file()
        }
    if actual_dlls != recorded_dlls:
        raise LicenseMaterialError(
            "FFmpeg runtime SHA-256 manifest does not match the staged shared DLL set: "
            f"expected {sorted(recorded_dlls)}, found {sorted(actual_dlls)}"
        )


def _validate_ffmpeg_material_paths(
    ffmpeg_dir: Path, runtime_dir: Path, *, staged: bool
) -> tuple[str, str]:
    source_archive = ffmpeg_dir / "Source" / SOURCE_ARCHIVE_NAME
    signature = ffmpeg_dir / "Source" / f"{SOURCE_ARCHIVE_NAME}.asc"
    release_key = ffmpeg_dir / "Source" / "ffmpeg-release-key.asc"
    build_script = ffmpeg_dir / "Source" / "build_ffmpeg.sh"
    fetch_script = ffmpeg_dir / "Source" / "fetch_ffmpeg.py"
    license_path = ffmpeg_dir / "LICENSE-LGPL-2.1.txt"
    metadata_path = ffmpeg_dir / "BUILD-METADATA.txt"
    source_offer = ffmpeg_dir / "SOURCE-OFFER.md"
    required = (
        source_archive,
        signature,
        release_key,
        build_script,
        fetch_script,
        license_path,
        metadata_path,
        source_offer,
    )
    missing = [path.name for path in required if not path.is_file() or not path.stat().st_size]
    if missing:
        raise LicenseMaterialError(
            "Required FFmpeg source/build/license material is missing or empty: "
            + ", ".join(missing)
        )

    if not _is_substantive_license(license_path.read_bytes()):
        raise LicenseMaterialError("The FFmpeg LGPL license text is insubstantial or incomplete")
    license_text = license_path.read_text(encoding="utf-8", errors="replace").casefold()
    if "lesser general public license" not in license_text or "version 2.1" not in license_text:
        raise LicenseMaterialError("The bundled FFmpeg license is not the full LGPL 2.1 text")
    if not _is_substantive_license(source_offer.read_bytes()):
        raise LicenseMaterialError("The FFmpeg source offer is missing or insubstantial")

    metadata_text = metadata_path.read_text(encoding="utf-8")
    actual_source_hash = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    recorded_source_hash = _metadata_value(metadata_text, "Source archive SHA-256").lower()
    if actual_source_hash != FFMPEG_SOURCE_SHA256 or recorded_source_hash != FFMPEG_SOURCE_SHA256:
        raise LicenseMaterialError(
            "FFmpeg source SHA-256 mismatch: expected pinned digest "
            f"{FFMPEG_SOURCE_SHA256}, metadata records {recorded_source_hash}, actual {actual_source_hash}"
        )
    if _metadata_value(metadata_text, "FFmpeg version") != FFMPEG_VERSION:
        raise LicenseMaterialError("FFmpeg build metadata does not match the pinned source version")
    if _metadata_value(metadata_text, "Source archive") != SOURCE_ARCHIVE_NAME:
        raise LicenseMaterialError("FFmpeg build metadata names an unexpected source archive")
    if _metadata_value(metadata_text, "Source URL") != SOURCE_URL:
        raise LicenseMaterialError("FFmpeg build metadata names an unexpected source URL")
    if _metadata_value(metadata_text, "Source signature") != f"{SOURCE_ARCHIVE_NAME}.asc":
        raise LicenseMaterialError("FFmpeg build metadata names an unexpected source signature")
    if _metadata_value(metadata_text, "Signature result") != "VALID":
        raise LicenseMaterialError("FFmpeg source signature was not verified by the build")
    if _metadata_value(metadata_text, "Release key fingerprint").upper() != RELEASE_KEY_FINGERPRINT:
        raise LicenseMaterialError("FFmpeg source signature used an unexpected release-key fingerprint")

    required_config = (
        "--disable-everything",
        "--disable-gpl",
        "--disable-version3",
        "--disable-nonfree",
        "--disable-autodetect",
        "--disable-network",
        "--enable-shared",
        "--disable-static",
    )
    missing_flags = [flag for flag in required_config if flag not in metadata_text]
    if missing_flags or re.search(r"--enable-(?:gpl|version3|nonfree)\b", metadata_text):
        raise LicenseMaterialError(
            "FFmpeg build metadata does not attest to the required LGPL-only configuration"
        )
    build_hash = hashlib.sha256(build_script.read_bytes()).hexdigest()
    if _metadata_value(metadata_text, "Build script SHA-256").lower() != build_hash:
        raise LicenseMaterialError("FFmpeg build-script SHA-256 does not match its included recipe")

    offer_text = source_offer.read_text(encoding="utf-8", errors="replace")
    if SOURCE_ARCHIVE_NAME not in offer_text or actual_source_hash not in offer_text:
        raise LicenseMaterialError("The FFmpeg source offer does not identify the exact pinned source")
    _validate_ffmpeg_source_archive(source_archive)
    _verify_runtime_hashes(metadata_text, runtime_dir, staged=staged)

    gcc_licenses = ffmpeg_dir / "GCC-RUNTIME-LICENSES"
    license_files = [path for path in gcc_licenses.rglob("*") if path.is_file()]
    if not any(_is_substantive_license(path.read_bytes()) for path in license_files):
        raise LicenseMaterialError("Bundled FFmpeg toolchain runtime license material is missing")
    return actual_source_hash, _metadata_value(metadata_text, "Build script SHA-256").lower()


def _validate_ffmpeg_release_bundle(license_dir: Path) -> tuple[str, str]:
    ffmpeg_dir = Path(license_dir) / "FFmpeg"
    return _validate_ffmpeg_material_paths(
        ffmpeg_dir, Path(license_dir).parent, staged=False
    )


def _copy_ffmpeg_material(license_dir: Path, repo_root: Path) -> str:
    source_dir = Path(repo_root) / "packaging" / "bin"
    metadata_path = source_dir / _FFMPEG_METADATA_FILE
    try:
        metadata_text = metadata_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise LicenseMaterialError(f"Required FFmpeg build metadata is absent or unreadable: {exc}") from exc

    copies = (
        (source_dir / SOURCE_ARCHIVE_NAME, Path("Source") / SOURCE_ARCHIVE_NAME),
        (source_dir / f"{SOURCE_ARCHIVE_NAME}.asc", Path("Source") / f"{SOURCE_ARCHIVE_NAME}.asc"),
        (source_dir / "ffmpeg-release-key.asc", Path("Source") / "ffmpeg-release-key.asc"),
        (source_dir / "build_ffmpeg.sh", Path("Source") / "build_ffmpeg.sh"),
        (source_dir / "fetch_ffmpeg.py", Path("Source") / "fetch_ffmpeg.py"),
        (source_dir / "FFMPEG-LICENSE-LGPL-2.1.txt", Path("LICENSE-LGPL-2.1.txt")),
        (metadata_path, Path("BUILD-METADATA.txt")),
        (source_dir / "FFMPEG-SOURCE-OFFER.md", Path("SOURCE-OFFER.md")),
    )
    missing = [source.name for source, _destination in copies if not source.is_file()]
    if missing:
        raise LicenseMaterialError(
            "Required FFmpeg source/signature/license/build material is missing: "
            + ", ".join(missing)
        )
    gcc_licenses = source_dir / "GCC-RUNTIME-LICENSES"
    if not gcc_licenses.is_dir():
        raise LicenseMaterialError("Required FFmpeg GCC runtime license directory is missing")
    try:
        metadata_text = metadata_path.read_text(encoding="utf-8")
        source_hash = hashlib.sha256((source_dir / SOURCE_ARCHIVE_NAME).read_bytes()).hexdigest()
        recorded_source_hash = _metadata_value(metadata_text, "Source archive SHA-256").lower()
    except (OSError, UnicodeError) as exc:
        raise LicenseMaterialError(f"FFmpeg source archive or build metadata is unreadable: {exc}") from exc
    if source_hash != FFMPEG_SOURCE_SHA256 or recorded_source_hash != FFMPEG_SOURCE_SHA256:
        raise LicenseMaterialError(
            "FFmpeg source SHA-256 mismatch: expected pinned digest "
            f"{FFMPEG_SOURCE_SHA256}, metadata records {recorded_source_hash}, actual {source_hash}"
        )
    _verify_runtime_hashes(metadata_text, source_dir, staged=True)

    ffmpeg_output = Path(license_dir) / "FFmpeg"
    for source, relative in copies:
        destination = ffmpeg_output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    shutil.copytree(gcc_licenses, ffmpeg_output / "GCC-RUNTIME-LICENSES", dirs_exist_ok=True)
    return source_hash


def collect_release_license_material(license_dir: Path, *, repo_root: Path) -> None:
    """Copy exact runtime license texts and archive provenance beside the application."""
    license_dir = Path(license_dir)
    license_dir.mkdir(parents=True, exist_ok=True)
    provenance: list[str] = []

    try:
        ffmpeg_source_hash = _copy_ffmpeg_material(license_dir, Path(repo_root))
        provenance.append(
            f"FFmpeg {FFMPEG_VERSION} source archive SHA-256: {ffmpeg_source_hash}"
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
            f"FFmpeg {FFMPEG_VERSION} was built from the pinned official source archive",
            f"{SOURCE_URL} with SHA-256 {ffmpeg_source_hash}.",
            "The build metadata records the signature verification, release-key fingerprint,",
            "feature configuration, and hashes of the executables and shared FFmpeg DLLs.",
            "This inventory is not a legal opinion; review all component and toolchain notices",
            "before redistribution.",
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
