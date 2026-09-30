from pathlib import Path


packaging_dir = Path(SPECPATH)
repo_root = packaging_dir.parent

datas = []
for binary_name in ("ffmpeg.exe", "ffprobe.exe"):
    binary_path = packaging_dir / "bin" / binary_name
    if binary_path.is_file():
        datas.append((str(binary_path), "."))

licenses_path = repo_root / "LICENSES"
if licenses_path.is_dir():
    datas.append((str(licenses_path), "LICENSES"))

excluded_modules = [
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.Qt3DCore",
    "PySide6.QtWebEngineCore",
    "pytest",
    "_pytest",
    "test",
    "tests",
    "nose",
    "unittest",
    "doctest",
    "hypothesis",
]

a = Analysis(
    [str(repo_root / "src" / "audio_transcriber" / "__main__.py")],
    pathex=[str(repo_root / "src")],
    binaries=[],
    datas=datas,
    # selftest is loaded by importlib from __main__, so PyInstaller cannot infer it.
    hiddenimports=["audio_transcriber.selftest"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AudioTranscriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    contents_directory=".",
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AudioTranscriber",
)
