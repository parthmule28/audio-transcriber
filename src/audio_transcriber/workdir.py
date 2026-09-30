"""Lifecycle helpers for temporary audio-processing workspaces."""

import ctypes
import errno
import json
import os
from pathlib import Path
import shutil
import tempfile


WORKSPACE_PREFIX = "audio-transcriber-"
OWNER_METADATA_FILENAME = ".audio-transcriber-owner.json"
_OWNER_APPLICATION = "AudioTranscriber"
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87
_STILL_ACTIVE = 259


def _windows_process_state(pid: int) -> str:
    """Query a Windows process without using destructive ``os.kill`` semantics."""
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
    except (AttributeError, OSError):
        return "unknown"

    if not handle:
        return "stale" if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER else "unknown"

    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return "unknown"
        return "active" if exit_code.value == _STILL_ACTIVE else "stale"
    except (AttributeError, OSError, TypeError, ValueError):
        return "unknown"
    finally:
        kernel32.CloseHandle(handle)


def _process_state(pid: int) -> str:
    """Return active, stale, or unknown; only a confirmed missing PID is stale."""
    if os.name == "nt":
        return _windows_process_state(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return "stale"
    except PermissionError:
        return "unknown"
    except OSError as error:
        if error.errno == errno.ESRCH:
            return "stale"
        return "unknown"
    return "active"


def _read_owner_pid(path: Path) -> int | None:
    try:
        metadata = json.loads((path / OWNER_METADATA_FILENAME).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(metadata, dict) or metadata.get("application") != _OWNER_APPLICATION:
        return None
    pid = metadata.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    return pid


class AudioWorkspace:
    """A lazily-created temporary directory for audio chunks."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._path: Path | None = None
        self._cleaned = False

    @property
    def path(self) -> Path:
        if self._path is None:
            if self._cleaned:
                raise RuntimeError("workspace has been cleaned up")
            self._path = Path(
                tempfile.mkdtemp(prefix=WORKSPACE_PREFIX, dir=self._root)
            )
            try:
                (self._path / OWNER_METADATA_FILENAME).write_text(
                    json.dumps({"application": _OWNER_APPLICATION, "pid": os.getpid()}),
                    encoding="utf-8",
                )
            except OSError:
                shutil.rmtree(self._path, ignore_errors=True)
                self._path = None
                raise
        return self._path

    def chunk_path(self, index: int) -> Path:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("chunk index must be a non-negative integer")
        return self.path / f"chunk_{index:04d}.wav"

    def cleanup(self) -> None:
        if self._path is not None:
            shutil.rmtree(self._path, ignore_errors=True)
        self._cleaned = True

    def __enter__(self) -> "AudioWorkspace":
        self.path
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.cleanup()


def cleanup_stale_workspaces(root: Path | None = None) -> int:
    """Remove only app-owned workspaces whose recorded process is confirmed dead.

    Missing, malformed, active, or inaccessible ownership data is left alone.
    """
    directory = Path(tempfile.gettempdir() if root is None else root)
    removed = 0
    for candidate in directory.iterdir():
        if (
            not candidate.is_symlink()
            and candidate.is_dir()
            and candidate.name.startswith(WORKSPACE_PREFIX)
        ):
            pid = _read_owner_pid(candidate)
            if pid is None or _process_state(pid) != "stale":
                continue
            try:
                shutil.rmtree(candidate)
            except OSError:
                continue
            removed += 1
    return removed
