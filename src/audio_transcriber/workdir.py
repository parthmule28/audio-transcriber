"""Lifecycle helpers for temporary audio-processing workspaces."""

from pathlib import Path
import shutil
import tempfile


WORKSPACE_PREFIX = "audio-transcriber-"


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
    """Remove directories belonging to this application under ``root``."""
    directory = Path(tempfile.gettempdir() if root is None else root)
    removed = 0
    for candidate in directory.iterdir():
        if candidate.is_dir() and candidate.name.startswith(WORKSPACE_PREFIX):
            try:
                shutil.rmtree(candidate)
            except OSError:
                continue
            removed += 1
    return removed
