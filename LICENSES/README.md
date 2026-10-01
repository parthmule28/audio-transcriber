# Third-party software and licenses

The Windows package contains this index, the full license texts and notices collected from the actual packaging environment, and the FFmpeg source/build provenance described below. Generated `BUILD-METADATA.txt` files record package versions, source inputs, build configuration, and artifact hashes. This inventory is factual packaging information, not a legal opinion.

| Component | Bundled component and license information | Included material |
| --- | --- | --- |
| FFmpeg and FFprobe | FFmpeg 9.0.2 built from the pinned official source archive using a feature-minimal UCRT64 configuration. GPL, version-3-only, nonfree, autodetection, and network features are disabled; FFmpeg shared libraries are included beside the executables. The build checks the runtime license banner and records its configuration. | `FFmpeg/LICENSE-LGPL-2.1.txt`, `FFmpeg/BUILD-METADATA.txt`, and under `FFmpeg/Source/`: the exact `.tar.xz` source, detached signature, release public key, source-fetch script, and build recipe. GCC runtime license texts are under `FFmpeg/GCC-RUNTIME-LICENSES/`. See [FFmpeg license information](https://ffmpeg.org/legal.html). |
| PySide6 | LGPL v3 and the applicable Qt GPL exception text | `PySide6/LGPL-3.0-only.txt`, `PySide6/Qt-GPL-exception-1.0.txt`; [Qt for Python license information](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt | LGPL v3 for the Qt libraries distributed with this application | `Qt/LGPL-3.0-only.txt`; [Qt license information and texts](https://doc.qt.io/qt-6/licenses-used-in-qt.html) |
| httpx | BSD 3-Clause | `httpx/LICENSE.md`, copied from installed wheel metadata; [httpx license](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| keyring | MIT | `keyring/LICENSE`, copied from installed wheel metadata; [keyring license](https://github.com/jaraco/keyring/blob/main/LICENSE) |
| Python | Python Software Foundation (PSF) License | `Python/LICENSE.txt`, copied from the Python runtime or its version-matched CPython source; [Python license](https://docs.python.org/3/license.html) |
| Python package environment | Active direct and transitive app/build dependencies on the Windows packaging runner, including PyInstaller and its bootloader | `Python-Packages.md` and per-distribution license files under `Python-Packages/` |

## FFmpeg build provenance

`packaging/build_ffmpeg.sh` fetches `https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz`, verifies its pinned SHA-256 and detached signature against the pinned FFmpeg release-key fingerprint, then builds the Windows runtime. The ZIP includes the matching source archive, signature, public key, build scripts, LGPL text, source offer, toolchain license material, and generated metadata. The packager rejects missing or altered source, license, build, or runtime hash material before creating the ZIP.

This repository does not make a legal-compliance guarantee. Review the exact built binaries, all linked/toolchain components and required notices before redistribution. See [`FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md`](FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md) for the remaining build-validation status.

The source tree keeps this index concise; full license texts and source/build materials are included in the generated Windows ZIP. The package collector resolves active transitive Python distribution requirements and fails closed if a required full license text is unavailable or insubstantial.
