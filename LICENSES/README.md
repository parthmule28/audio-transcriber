# Third-party software and licenses

The Windows release bundles the components below. Follow the linked license texts and notices for the exact versions and binaries included in each release.

| Component | Bundled component and applicable license | License text / notices |
| --- | --- | --- |
| FFmpeg and FFprobe | BtbN `ffmpeg-master-latest-win64-gpl.zip` — the Windows x64, static `gpl` variant fetched by `packaging/fetch_ffmpeg.py`. This is the GPL build, not the LGPL-only variant. BtbN's GPL build enables GPL and version-3 components, so FFmpeg is GPL v3; included external libraries may carry additional notices. | [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), [FFmpeg license information](https://ffmpeg.org/legal.html), [GPL v3 text](https://github.com/FFmpeg/FFmpeg/blob/master/COPYING.GPLv3), [LGPL v2.1 text](https://github.com/FFmpeg/FFmpeg/blob/master/COPYING.LGPLv2.1) |
| PySide6 | LGPL v3 | [Qt for Python license information](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt | LGPL v3 for the Qt libraries distributed with this application | [Qt license information and texts](https://doc.qt.io/qt-6/licenses-used-in-qt.html) |
| httpx | BSD 3-Clause | [httpx license](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| keyring | MIT | [keyring license](https://github.com/jaraco/keyring/blob/main/LICENSE) |
| Python | Python Software Foundation (PSF) License | [Python license](https://docs.python.org/3/license.html) |

## How to comply

Before packaging a release, copy the applicable full license texts, copyright notices, and other required notices for the exact dependency and FFmpeg builds into this `LICENSES/` directory. The PyInstaller spec bundles this directory with the application. Keep the notices with redistributed copies, observe the applicable GPL and LGPL source and redistribution requirements, and check the actual build's configuration and included-library notices; this index is not legal advice.

This index points to upstream license materials and does not reproduce their full texts.
