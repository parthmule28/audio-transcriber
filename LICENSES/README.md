# Third-party software and licenses

The Windows release bundle is intended to contain the components below. [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) is an index; the release packager derives the direct and transitive Python distribution inventory from the Windows packaging environment and copies substantive license texts/notices, Python runtime material, and fetched FFmpeg material into the ZIP's `LICENSES/` directory. `Python-Packages.md` records the resolved package versions and paths, including PyInstaller and its bootloader. Generated `BUILD-METADATA.txt` files record provenance.

| Component | Bundled component and applicable license | License text / notices |
| --- | --- | --- |
| FFmpeg and FFprobe | BtbN `ffmpeg-master-latest-win64-gpl.zip` — the Windows x64, static `gpl` variant fetched by `packaging/fetch_ffmpeg.py`. This remains the approved unpinned upstream URL. | `FFmpeg/LICENSE.txt`, `FFmpeg/BUILD-METADATA.txt`, and (required before packaging) `FFmpeg/Source/ffmpeg-corresponding-source.tar.xz`, `FFmpeg/SOURCE-METADATA.txt`, `FFmpeg/SOURCE-OFFER.md`; [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), [FFmpeg license information](https://ffmpeg.org/legal.html) |
| PySide6 | LGPL v3 with the Qt GPL exception text | `PySide6/LGPL-3.0-only.txt`, `PySide6/Qt-GPL-exception-1.0.txt`; [Qt for Python license information](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt | LGPL v3 for the Qt libraries distributed with this application | `Qt/LGPL-3.0-only.txt`; [Qt license information and texts](https://doc.qt.io/qt-6/licenses-used-in-qt.html) |
| httpx | BSD 3-Clause | `httpx/LICENSE.md`, copied from the installed wheel metadata; [httpx license](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| keyring | MIT | `keyring/LICENSE`, copied from the installed wheel metadata; [keyring license](https://github.com/jaraco/keyring/blob/main/LICENSE) |
| Python | Python Software Foundation (PSF) License | `Python/LICENSE.txt`, copied from the Python runtime or its version-matched CPython source; [Python license](https://docs.python.org/3/license.html) |
| Python package environment | All active direct/transitive app and PyInstaller build dependencies installed on the Windows packaging runner, including PyInstaller's bootloader package | `Python-Packages.md` and per-distribution license files under `Python-Packages/` |

## Current FFmpeg source-compliance blocker

**Do not publish or redistribute a release ZIP at this time.** The unpinned BtbN `latest` GPL archive provides a license file and a post-download digest, but this repository does not contain the exact corresponding source archive or a verified written source offer. A digest identifies fetched bytes; it does not establish source correspondence. `packaging/build_release.py` fails closed until the required source archive, matching metadata, maintainer verification evidence, and written offer are supplied. See [`FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md`](FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md) and `packaging/ffmpeg-source-compliance/README.md` for the exact materials required. No legal-compliance claim is made.

## How to comply

The source tree keeps this index concise; the packager stages full texts/notices and fails before writing the ZIP if any required material is missing or insubstantial. It resolves active transitive distribution requirements and requires full license assets for every distribution, including PyInstaller. It also requires a readable FFmpeg source archive whose recorded binary digest matches the fetched archive, a source digest, maintainer verification evidence, and a written source offer. The BtbN `latest` URL remains unpinned as required by the approved packaging plan; its recorded digest is traceability only, not a pinned checksum. Review the actual FFmpeg build and every linked-library notice before redistribution. This index is not legal advice.

The index points to the release ZIP's copied license materials and upstream sources; full license texts are not pasted into this README.
