# Third-party notices

This file identifies third-party components intended for the Windows application and summarizes their licenses. It is an index, not a copy of any license text. **Full license texts are not included in this notice file.** The release builder places full texts/notices in this `LICENSES/` directory and records their sources in `BUILD-METADATA.txt`. It fails closed if material is missing or insubstantial. Review the actual FFmpeg build for every external-library notice required for redistribution.

## FFmpeg and FFprobe

The application bundles `ffmpeg.exe` and `ffprobe.exe` from BtbN's Windows x64 static GPL archive, `ffmpeg-master-latest-win64-gpl.zip`, fetched from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds). This GPL build enables GPL and version-3 components; FFmpeg is distributed under GPL v3 in this build. Other libraries compiled into the FFmpeg binaries may carry separate copyright and license notices. See [FFmpeg license information](https://ffmpeg.org/legal.html), the [GPL v3 text](https://github.com/FFmpeg/FFmpeg/blob/master/COPYING.GPLv3), and the [LGPL v2.1 text](https://github.com/FFmpeg/FFmpeg/blob/master/COPYING.LGPLv2.1).

**Release blocker:** the archive download currently supplies no exact corresponding source archive or written source offer in this repository. Its unpinned URL and recorded SHA-256 are not evidence of source correspondence. Release ZIP creation and publishing fail until a maintainer establishes and supplies the exact source, matching binary/source hashes, and offer described in [`FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md`](FFMPEG-SOURCE-COMPLIANCE-BLOCKER.md). No compliance claim is made.

## PySide6 and Qt

PySide6 and the Qt libraries are distributed under the LGPL v3 terms applicable to the components used. See [Qt for Python license information](https://doc.qt.io/qtforpython-6/licenses.html) and [Qt license information and texts](https://doc.qt.io/qt-6/licenses-used-in-qt.html).

## Python dependencies and runtime

- **httpx** — BSD 3-Clause. See the [httpx license](https://github.com/encode/httpx/blob/master/LICENSE.md).
- **keyring** — MIT. See the [keyring license](https://github.com/jaraco/keyring/blob/main/LICENSE).
- **Python** — Python Software Foundation (PSF) License. See the [Python license](https://docs.python.org/3/license.html).

The generated [`Python-Packages.md`](Python-Packages.md) inventories direct and transitive packages from the actual Windows packaging environment, including PyInstaller and its bootloader. Each listed distribution's substantive license assets are copied under `Python-Packages/`; packaging fails if a required distribution or full license text is missing.
