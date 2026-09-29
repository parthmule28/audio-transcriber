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


def test_cleanup_stale_only_touches_our_prefix(tmp_path):
    keep = tmp_path / "someone-elses-data"
    keep.mkdir()
    stale = tmp_path / (WORKSPACE_PREFIX + "old")
    stale.mkdir()
    assert cleanup_stale_workspaces(tmp_path) == 1
    assert keep.is_dir() and not stale.exists()
