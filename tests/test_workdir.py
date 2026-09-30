import ctypes
import json
import os
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from audio_transcriber import workdir
from audio_transcriber.workdir import (
    OWNER_METADATA_FILENAME,
    WORKSPACE_PREFIX,
    AudioWorkspace,
    cleanup_stale_workspaces,
)


class FakeWin32Function:
    def __init__(self, function):
        self.function = function
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.function(*args)


def _mock_windows_process_api(monkeypatch, *, exit_code=259, open_error=0):
    calls = []
    handle = 1234

    def open_process(access, inherit, pid):
        calls.append(("open", access, inherit, pid))
        return 0 if open_error else handle

    def get_exit_code(opened_handle, result):
        calls.append(("exit", opened_handle))
        result._obj.value = exit_code
        return 1

    def close_handle(opened_handle):
        calls.append(("close", opened_handle))
        return 1

    kernel32 = SimpleNamespace(
        OpenProcess=FakeWin32Function(open_process),
        GetExitCodeProcess=FakeWin32Function(get_exit_code),
        CloseHandle=FakeWin32Function(close_handle),
    )
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, use_last_error: kernel32, raising=False
    )
    monkeypatch.setattr(ctypes, "get_last_error", lambda: open_error, raising=False)

    class FakeWindowsOS:
        name = "nt"

        @staticmethod
        def kill(*_args):
            pytest.fail("Windows process state checks must not call os.kill")

    monkeypatch.setattr(workdir, "os", FakeWindowsOS)
    return calls


def test_windows_process_state_uses_non_destructive_process_query(monkeypatch):
    calls = _mock_windows_process_api(monkeypatch)

    assert workdir._process_state(12345) == "active"
    assert calls == [
        ("open", 0x1000, False, 12345),
        ("exit", 1234),
        ("close", 1234),
    ]


def test_windows_process_state_treats_missing_and_inaccessible_pids_safely(monkeypatch):
    calls = _mock_windows_process_api(monkeypatch, exit_code=0)
    assert workdir._process_state(12345) == "stale"
    assert calls[-1] == ("close", 1234)

    _mock_windows_process_api(monkeypatch, open_error=87)
    assert workdir._process_state(12345) == "stale"

    _mock_windows_process_api(monkeypatch, open_error=5)
    assert workdir._process_state(12345) == "unknown"


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
    (stale / OWNER_METADATA_FILENAME).write_text(
        json.dumps({"application": "AudioTranscriber", "pid": os.getpid() + 100000}),
        encoding="utf-8",
    )
    with patch("audio_transcriber.workdir._process_state", return_value="stale"):
        assert cleanup_stale_workspaces(tmp_path) == 1
    assert keep.is_dir() and not stale.exists()


def test_cleanup_preserves_two_live_owners_and_removes_only_confirmed_stale_owner(
    tmp_path, monkeypatch
):
    active_one = AudioWorkspace(root=tmp_path)
    active_two = AudioWorkspace(root=tmp_path)
    active_paths = (active_one.path, active_two.path)
    stale = tmp_path / (WORKSPACE_PREFIX + "stale")
    stale.mkdir()
    (stale / OWNER_METADATA_FILENAME).write_text(
        json.dumps({"application": "AudioTranscriber", "pid": 900001}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "audio_transcriber.workdir._process_state",
        lambda pid: "stale" if pid == 900001 else "active",
    )

    assert cleanup_stale_workspaces(tmp_path) == 1
    assert all(path.is_dir() for path in active_paths)
    assert not stale.exists()


def test_cleanup_preserves_unknown_or_unowned_workspace_directories(tmp_path, monkeypatch):
    unknown = tmp_path / (WORKSPACE_PREFIX + "unknown")
    unknown.mkdir()
    (unknown / OWNER_METADATA_FILENAME).write_text(
        json.dumps({"application": "AudioTranscriber", "pid": 900002}),
        encoding="utf-8",
    )
    unowned = tmp_path / (WORKSPACE_PREFIX + "unowned")
    unowned.mkdir()
    monkeypatch.setattr("audio_transcriber.workdir._process_state", lambda _pid: "unknown")

    assert cleanup_stale_workspaces(tmp_path) == 0
    assert unknown.is_dir() and unowned.is_dir()


def test_cleanup_stale_continues_after_removal_error(tmp_path):
    failed = tmp_path / (WORKSPACE_PREFIX + "failed")
    failed.mkdir()
    (failed / OWNER_METADATA_FILENAME).write_text(
        json.dumps({"application": "AudioTranscriber", "pid": os.getpid() + 100000}),
        encoding="utf-8",
    )
    removed = tmp_path / (WORKSPACE_PREFIX + "removed")
    removed.mkdir()
    (removed / OWNER_METADATA_FILENAME).write_text(
        json.dumps({"application": "AudioTranscriber", "pid": os.getpid() + 100001}),
        encoding="utf-8",
    )
    real_rmtree = shutil.rmtree

    def remove_or_fail(path, *args, **kwargs):
        if path == failed:
            raise OSError("cannot remove")
        return real_rmtree(path, *args, **kwargs)

    with patch("audio_transcriber.workdir.shutil.rmtree", side_effect=remove_or_fail):
        with patch("audio_transcriber.workdir._process_state", return_value="stale"):
            assert cleanup_stale_workspaces(tmp_path) == 1

    assert failed.is_dir()
    assert not removed.exists()
