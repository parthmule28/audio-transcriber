import shutil
from unittest.mock import patch

import pytest

from audio_transcriber.workdir import (
    WORKSPACE_PREFIX,
    AudioWorkspace,
    cleanup_stale_workspaces,
)


def test_workspace_is_created_and_removed(tmp_path):
    with AudioWorkspace(root=tmp_path) as ws:
        assert ws.path.is_dir()
        assert ws.path.name.startswith(WORKSPACE_PREFIX)
        assert ws.chunk_path(3).name == "chunk_0003.wav"
        saved = ws.path
    assert not saved.exists()


def test_cleanup_is_idempotent(tmp_path):
    ws = AudioWorkspace(root=tmp_path)
    path = ws.path
    assert path.is_dir()
    ws.cleanup()
    ws.cleanup()
    assert not path.exists()


def test_access_after_cleanup_does_not_leave_a_workspace(tmp_path):
    ws = AudioWorkspace(root=tmp_path)
    original_path = ws.path
    ws.cleanup()

    assert ws.path == original_path
    assert not original_path.exists()
    assert list(tmp_path.iterdir()) == []
    ws.chunk_path(2)
    ws.cleanup()
    assert list(tmp_path.iterdir()) == []


def test_workspace_creation_is_lazy(tmp_path):
    ws = AudioWorkspace(root=tmp_path)
    assert list(tmp_path.iterdir()) == []
    ws.cleanup()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("index", [-1, True, 1.5, "2"])
def test_chunk_path_rejects_unsafe_indices(tmp_path, index):
    ws = AudioWorkspace(root=tmp_path)
    with pytest.raises(ValueError):
        ws.chunk_path(index)
    assert list(tmp_path.iterdir()) == []


def test_cleanup_stale_only_touches_our_prefix(tmp_path):
    keep = tmp_path / "someone-elses-data"
    keep.mkdir()
    stale = tmp_path / (WORKSPACE_PREFIX + "old")
    stale.mkdir()
    assert cleanup_stale_workspaces(tmp_path) == 1
    assert keep.is_dir() and not stale.exists()


def test_cleanup_stale_continues_after_removal_error(tmp_path):
    failed = tmp_path / (WORKSPACE_PREFIX + "failed")
    failed.mkdir()
    removed = tmp_path / (WORKSPACE_PREFIX + "removed")
    removed.mkdir()
    real_rmtree = shutil.rmtree

    def remove_or_fail(path, *args, **kwargs):
        if path == failed:
            raise OSError("cannot remove")
        return real_rmtree(path, *args, **kwargs)

    with patch("audio_transcriber.workdir.shutil.rmtree", side_effect=remove_or_fail):
        assert cleanup_stale_workspaces(tmp_path) == 1

    assert failed.is_dir()
    assert not removed.exists()
