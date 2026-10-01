# Third-party notices

This file identifies third-party components intended for the Windows application and summarizes their licenses. It is an index, not a copy of any license text. **Full license texts and FFmpeg source/build materials are included in the Windows ZIP** under `LICENSES/`; `BUILD-METADATA.txt` records their provenance. Review the actual FFmpeg build and all toolchain dependencies before redistribution. This notice is not a legal opinion.

## FFmpeg and FFprobe

The application bundles `ffmpeg.exe`, `ffprobe.exe`, and replaceable shared FFmpeg DLLs built from the pinned official FFmpeg 9.0.2 source archive. The build configuration disables GPL, version-3-only, nonfree, autodetection, and network features and enables only the local file protocol and the reviewed demuxer/decoder/filter/encoder/muxer set. The release build checks the FFmpeg license banner and records hashes for both executables and every FFmpeg DLL.

The ZIP includes the exact `ffmpeg-9.0.2.tar.xz` source archive, its detached signature, the release public key, the LGPL v2.1 license text (`COPYING.LGPLv2.1`), the UCRT64 build and fetch scripts, a source offer, generated build metadata, and GCC runtime license material. See [FFmpeg license information](https://ffmpeg.org/legal.html). The source archive contains upstream project files with their respective notices; the build metadata identifies the configuration used for the bundled runtime. No legal-compliance guarantee is made.

## PySide6 and Qt

PySide6 and the Qt libraries are distributed under the LGPL v3 terms applicable to the components used. See [Qt for Python license information](https://doc.qt.io/qtforpython-6/licenses.html) and [Qt license information and texts](https://doc.qt.io/qt-6/licenses-used-in-qt.html).

## Python dependencies and runtime

- **httpx** — BSD 3-Clause. See the [httpx license](https://github.com/encode/httpx/blob/master/LICENSE.md).
- **keyring** — MIT. See the [keyring license](https://github.com/jaraco/keyring/blob/main/LICENSE).
- **Python** — Python Software Foundation (PSF) License. See the [Python license](https://docs.python.org/3/license.html).

The generated [`Python-Packages.md`](Python-Packages.md) inventories direct and transitive packages from the actual Windows packaging environment, including PyInstaller and its bootloader. Each listed distribution's substantive license assets are copied under `Python-Packages/`; packaging fails if a required distribution or full license text is missing.
