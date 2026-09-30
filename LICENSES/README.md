# Third-party software and licenses

The Windows release bundles the components below. [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) is an index; the release packager copies the required license texts/notices from the installed wheels, Python runtime, and fetched FFmpeg archive into the ZIP's `LICENSES/` directory. The generated `BUILD-METADATA.txt` files record the source versions and archive material.

| Component | Bundled component and applicable license | License text / notices |
| --- | --- | --- |
| FFmpeg and FFprobe | BtbN `ffmpeg-master-latest-win64-gpl.zip` — the Windows x64, static `gpl` variant fetched by `packaging/fetch_ffmpeg.py`. This is the GPL build, not the LGPL-only variant. | `FFmpeg/LICENSE.txt` (copied from the fetched archive) and `FFmpeg/BUILD-METADATA.txt`; [BtbN FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds), [FFmpeg license information](https://ffmpeg.org/legal.html) |
| PySide6 | LGPL v3 with the Qt GPL exception text | `PySide6/LGPL-3.0-only.txt`, `PySide6/Qt-GPL-exception-1.0.txt`; [Qt for Python license information](https://doc.qt.io/qtforpython-6/licenses.html) |
| Qt | LGPL v3 for the Qt libraries distributed with this application | `Qt/LGPL-3.0-only.txt`; [Qt license information and texts](https://doc.qt.io/qt-6/licenses-used-in-qt.html) |
| httpx | BSD 3-Clause | `httpx/LICENSE.md`, copied from the installed wheel metadata; [httpx license](https://github.com/encode/httpx/blob/master/LICENSE.md) |
| keyring | MIT | `keyring/LICENSE`, copied from the installed wheel metadata; [keyring license](https://github.com/jaraco/keyring/blob/main/LICENSE) |
| Python | Python Software Foundation (PSF) License | `Python/LICENSE.txt`, copied from the Python runtime or its version-matched CPython source; [Python license](https://docs.python.org/3/license.html) |

## How to comply

The source tree keeps this index concise; `packaging/build_release.py` stages the required full texts/notices into the application ZIP and fails before writing the ZIP if required material is absent or empty. The builder reuses license files from installed wheel metadata and the BtbN archive, and uses version-tagged upstream Qt/PySide6 and CPython license sources only when the corresponding installed files are unavailable. Keep all notices with redistributed copies and observe the applicable GPL and LGPL source and redistribution requirements. The BtbN `latest` URL remains unpinned as required by the packaging plan; review the actual FFmpeg build and any additional linked-library notices before redistribution. This index is not legal advice.

The index points to the release ZIP's copied license materials and upstream sources; full license texts are not pasted into this README.
