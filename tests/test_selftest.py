from types import SimpleNamespace

from audio_transcriber.selftest import run_self_test


def fake_probe_ok(command, *, timeout):
    return SimpleNamespace(returncode=0, stdout="ffmpeg version test", stderr="")


def fake_probe_missing_ffmpeg(name):
    if name == "ffmpeg":
        raise FileNotFoundError("ffmpeg missing")
    return "/fake/ffprobe"


def test_self_test_reports_qt_and_ffmpeg_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_self_test(probe_fn=fake_probe_ok, binary_probe=lambda name: f"/fake/{name}")
    names = [name for name, _, _ in result.checks]
    assert names == ["python-version", "qt-initialised", "ffmpeg", "ffprobe"]
    assert result.ok is True


def test_self_test_fails_when_a_binary_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_self_test(probe_fn=fake_probe_ok, binary_probe=fake_probe_missing_ffmpeg)
    assert result.ok is False
    assert next(ok for name, ok, _ in result.checks if name == "ffmpeg") is False


def test_self_test_writes_identical_summary_to_log(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    result = run_self_test(probe_fn=fake_probe_ok, binary_probe=lambda name: f"/fake/{name}")
    output = capsys.readouterr().out
    assert (tmp_path / "self-test.log").read_text() == output
    assert all(name in output for name, _, _ in result.checks)


def test_self_test_makes_no_network_call_and_reads_no_credential(monkeypatch, tmp_path):
    import keyring
    import socket

    def boom(*args, **kwargs):
        raise AssertionError("forbidden access")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(keyring, "get_password", boom)
    monkeypatch.chdir(tmp_path)
    assert run_self_test(probe_fn=fake_probe_ok, binary_probe=lambda name: f"/fake/{name}").ok
